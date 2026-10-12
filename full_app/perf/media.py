"""FFmpeg execution, conservative keyframe cuts and validated copy concat."""
import json
import subprocess
import tempfile
from pathlib import Path


def run(cmd):
    result = subprocess.run([str(x) for x in cmd], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return result


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_data", "-of", "json", path]).stdout)


def copy_cut(source, output, start, end):
    """Copy only exact keyframe boundaries (or EOF); return False for accurate fallback."""
    if not 0 <= start < end:
        raise ValueError("invalid cut interval")
    info = probe(source)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    # Open GOPs / reordered frames require more than a keyframe timestamp check.
    # Decline rather than risk leading/trailing pictures outside the requested cut.
    if video.get("has_b_frames", 0):
        return False
    duration = float(info["format"]["duration"])
    frames = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                            "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", source]).stdout)
    keys = [float(f["best_effort_timestamp_time"]) for f in frames["frames"]]
    aligned = lambda t: any(abs(t - k) < 0.0001 for k in keys)
    if not aligned(start) or not (aligned(end) or abs(end - duration) < .001):
        return False
    run(["ffmpeg", "-v", "error", "-y", "-ss", start, "-i", source, "-t", end-start,
         "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", output])
    return True


def concatenate(paths, output):
    """Reject unlike stream parameters rather than silently produce a broken montage."""
    fields = ("codec_name", "codec_type", "profile", "level", "width", "height", "pix_fmt", "r_frame_rate",
              "time_base", "sample_rate", "channels", "channel_layout", "extradata")
    paths = [Path(p).resolve() for p in paths]
    if not paths:
        raise ValueError("no clips")
    signatures = [tuple(tuple(s.get(k) for k in fields) for s in probe(p)["streams"]) for p in paths]
    if any(s != signatures[0] for s in signatures[1:]):
        raise ValueError("concat requires identical stream parameters and codec extradata")
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "concat.txt"
        if any("\n" in str(p) or "\r" in str(p) for p in paths):
            raise ValueError("newline in media path")
        listing.write_text("".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in paths), encoding="utf-8")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", output])
    return Path(output)
