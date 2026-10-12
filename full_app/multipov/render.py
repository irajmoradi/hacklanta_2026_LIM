"""CPU FFmpeg renderer with clock correction and literal player name tags."""
from pathlib import Path
import math
import os
import subprocess
import tempfile

from .models import normalize
from .sync import probe


def _run(args, cwd):
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args],
                            cwd=cwd, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-2000:])


def render_montage(videos, candidates, output, *, offsets, mode="best", width=1280, height=720, fps=30):
    """Render chronological highlights with name tags and a full team credit.

    mode: best, split, or pip. Replays use the two highest scoring angles;
    single-angle highlights fill the canvas. Audio comes only from the best
    angle, avoiding echoes. Alignment records must correspond to input order.
    """
    videos = normalize(videos)
    offsets, candidates = list(offsets), sorted(candidates, key=lambda c: c.start)
    if len(offsets) != len(videos) or not candidates:
        raise ValueError("nonempty candidates and one alignment per video required")
    if mode not in ("best", "split", "pip"):
        raise ValueError("mode must be best, split, or pip")
    if (not isinstance(width, int) or not isinstance(height, int) or width < 320 or height < 180
            or width % 4 or height % 4 or not math.isfinite(fps) or not 1 <= fps <= 120):
        raise ValueError("canvas must be >=320x180, divisible by four; fps must be 1..120")
    output = Path(output).resolve()
    if output in {v.path for v in videos}:
        raise ValueError("output cannot overwrite a source recording")
    metadata = [probe(v.path) for v in videos]
    # Validate every interval before starting work or replacing an existing output.
    for candidate in candidates:
        if not all(math.isfinite(t) for t in (candidate.start, candidate.end)) or candidate.end <= candidate.start:
            raise ValueError("invalid match interval")
        if not candidate.angles:
            raise ValueError("candidate has no angles")
        for angle in candidate.angles:
            i = angle.video_index
            if not 0 <= i < len(videos):
                raise ValueError("invalid video index")
            if (offsets[i].to_local(candidate.start) < -1e-6 or
                    offsets[i].to_local(candidate.end) > metadata[i][0] + 1e-6):
                raise ValueError("match interval extends outside a recording")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="multipov-", dir=output.parent) as folder:
        work = Path(folder)
        # textfile + expansion=none keeps quotes, colons, percent signs and
        # filtergraph punctuation in user names out of FFmpeg's parser.
        (work / "team.txt").write_text("Team: " + " | ".join(v.player for v in videos), encoding="utf-8")
        for i, video in enumerate(videos):
            (work / f"name{i}.txt").write_text(video.player, encoding="utf-8")
            (work / f"pov{i}.txt").write_text(f"From {video.player}'s POV...", encoding="utf-8")
        fontsize = max(14, height // 30)
        encoder = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
        for segment, candidate in enumerate(candidates):
            angles = candidate.angles[:1 if mode == "best" else 2]
            duration = candidate.end - candidate.start
            inputs, filters = [], []
            for slot, angle in enumerate(angles):
                i = angle.video_index
                alignment = offsets[i]
                local_start = max(0, alignment.to_local(candidate.start))
                inputs += ["-ss", f"{local_start:.9f}", "-t", f"{duration / alignment.rate:.9f}",
                           "-i", str(videos[i].path)]
                w, h = width, height
                if len(angles) == 2 and mode == "split":
                    w = width // 2
                elif len(angles) == 2 and mode == "pip" and slot == 1:
                    w, h = (width // 3) // 2 * 2, (height // 3) // 2 * 2
                label = f"pov{i}.txt" if slot == 1 else f"name{i}.txt"
                filters.append(
                    f"[{slot}:v:0]setpts=(PTS-STARTPTS)*{alignment.rate:.12f},fps={fps},"
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                    f"tpad=stop_mode=clone:stop_duration=1,trim=duration={duration},"
                    f"drawtext=textfile={label}:expansion=none:fontsize={max(12, min(fontsize, h // 10))}:"
                    f"fontcolor=white:box=1:boxcolor=black@0.7:x=8:y=8[v{slot}]"
                )
            if len(angles) == 2:
                composition = "hstack=inputs=2:shortest=1" if mode == "split" else "overlay=W-w-12:H-h-48:shortest=1"
                filters.append(f"[v0][v1]{composition}[composed]")
            else:
                filters.append("[v0]null[composed]")
            filters.append(f"[composed]drawtext=textfile=team.txt:expansion=none:fontsize={fontsize}:"
                           "fontcolor=white:box=1:boxcolor=black@0.7:x=8:y=h-th-8[outv]")
            best = angles[0].video_index
            if metadata[best][1]:
                filters.append(f"[0:a:0]asetpts=PTS-STARTPTS,atempo={1 / offsets[best].rate:.12f},"
                               f"aresample=48000,apad,atrim=duration={duration}[outa]")
            else:
                filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[outa]")
            _run([*inputs, "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
                  "-map", "[outv]", "-map", "[outa]", "-t", str(duration), *encoder,
                  f"segment{segment}.mp4"], work)
        (work / "concat.txt").write_text("".join(f"file 'segment{i}.mp4'\n" for i in range(len(candidates))), encoding="utf-8")
        _run(["-f", "concat", "-safe", "1", "-i", "concat.txt", "-c", "copy",
              "-movflags", "+faststart", "result.mp4"], work)
        os.replace(work / "result.mp4", output)
    return output
