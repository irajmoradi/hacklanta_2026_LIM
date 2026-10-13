"""FFmpeg command builder and executor — extract segments, overlay SFX, concatenate.

Uses NVENC GPU acceleration when available, falls back to libx264.
Supports multiple VFX per clip via ordered filter chaining.
"""

import subprocess
import os
from pathlib import Path

from models.effects import VIDEO_EFFECTS, SOUND_EFFECTS, build_vf_chain
from render.contracts import RenderFailure


def _detect_nvenc() -> bool:
    """Check if h264_nvenc is available."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


HAS_NVENC = _detect_nvenc()


class FFmpegRunner:
    def __init__(self, workspace: Path, source: Path, width: int, height: int, fps: float, *, perf=None):
        self.workspace = workspace
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self.perf = os.getenv('LIM_PERF', '1') != '0' if perf is None else perf
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.perf:
            from perf.cache import Cache
            self.cache = Cache(self.workspace / 'sfx_cache')

    def _encoder_args(self) -> list[str]:
        """Return encoder args — NVENC if available, else libx264."""
        if HAS_NVENC:
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22"]
        return ["-c:v", "libx264", "-crf", "22", "-preset", "veryfast", "-threads", "0"]

    def _run(self, cmd: list[str], label: str = "") -> subprocess.CompletedProcess:
        print(f"  [ffmpeg] {label}: {' '.join(cmd[:8])}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RenderFailure(f'Rendering failed ({label or "FFmpeg"}).') from RuntimeError(result.stderr[-500:])
        return result

    def extract_segment(self, index: int, start: float, end: float,
                        video_effects: list[str] | str = "none",
                        speed: float = 1.0) -> Path:
        """Extract a clip from source with optional effects and speed change."""
        output = self.workspace / f"seg_{index:03d}.mp4"

        # Trim the input timeline before applying speed filters. Output-side
        # -to otherwise truncates slowed clips back to their original duration.
        cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}",
               "-t", f"{end - start:.3f}", "-i", str(self.source)]

        # Normalize to list
        if isinstance(video_effects, str):
            vfx_list = [video_effects] if video_effects != "none" else []
        else:
            vfx_list = [v for v in video_effects if v != "none"]

        if 'chromatic_aberration' in vfx_list:
            base = self.extract_segment(index, start, end,
                                        [v for v in vfx_list if v != 'chromatic_aberration'], speed)
            output2 = self.workspace / f'seg_{index:03d}_ca.mp4'
            vf, _ = build_vf_chain(['chromatic_aberration'], self.width, self.height, int(self.fps))
            graph = (f'[0:v]{vf},scale={self.width}:{self.height},setsar=1[outv]')
            self._run(['ffmpeg', '-y', '-filter_complex_threads', '1', '-i', str(base),
                       '-filter_complex', graph, '-map', '[outv]', '-map', '0:a?',
                       *self._encoder_args(), '-c:a', 'copy', str(output2)], 'chromatic')
            output2.replace(output)
            return output

        # Build VFX chain
        vf_extra, af_extra = build_vf_chain(vfx_list, self.width, self.height, int(self.fps))

        vf_parts = ["setpts=PTS-STARTPTS"]
        af_parts = ["asetpts=PTS-STARTPTS"]

        # Apply speed
        if speed != 1.0:
            vf_parts.append(f"setpts={1.0/speed}*PTS")
            s = speed
            while s > 2.0:
                af_parts.append("atempo=2.0")
                s /= 2.0
            while s < 0.5:
                af_parts.append("atempo=0.5")
                s *= 2.0
            af_parts.append(f"atempo={s:.4f}")

        # Append VFX chain (already ordered by category)
        if vf_extra:
            vf_parts.append(vf_extra)

        if af_extra:
            af_parts.append(af_extra)

        if 'fade_out' in vfx_list:
            factor = (2 if 'slow_motion' in vfx_list else 1) * (.5 if 'speed_2x' in vfx_list else 1)
            duration = (end-start) / speed * factor
            length = min(1, duration)
            vf_parts.append(f'fps={self.fps},fade=t=out:st={duration-length}:d={length}')

        # Force consistent output resolution for concat
        vf_parts.append(f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease")
        vf_parts.append(f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2")

        cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-af", ",".join(af_parts)]
        cmd += self._encoder_args()
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        cmd += [str(output)]

        self._run(cmd, f"extract seg {index}")
        return output

    def overlay_sfx(self, segment_path: Path, sfx_entries: list[dict], index: int) -> Path:
        """Mix sound effect files into a segment at specified offsets."""
        valid = []
        for sfx in sfx_entries:
            sfx_info = SOUND_EFFECTS.get(sfx.get("sfx_key", ""), {})
            fpath = sfx_info.get("file")
            if fpath and Path(fpath).exists():
                valid.append(dict(file=fpath, offset=sfx.get('offset_in_segment', 0),
                                  duration=sfx.get('duration'), gain=sfx.get('gain', .7)))

        if not valid:
            return segment_path

        output = self.workspace / f"seg_{index:03d}_sfx.mp4"
        cmd = ["ffmpeg", "-y", "-i", str(segment_path)]

        filter_parts = []
        for i, sfx in enumerate(valid, start=1):
            cmd += ["-i", sfx["file"]]
            delay_ms = int(sfx["offset"] * 1000)
            trim = f"atrim=duration={sfx['duration']}," if sfx.get("duration") else ""
            filter_parts.append(
                f"[{i}:a]{trim}adelay={delay_ms}|{delay_ms},volume={sfx['gain']}[sfx{i}]"
            )

        sfx_labels = "".join(f"[sfx{i}]" for i in range(1, len(valid) + 1))
        mix_count = 1 + len(valid)
        filter_parts.append(
            f"[0:a]{sfx_labels}amix=inputs={mix_count}:duration=first[outa]"
        )

        cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += ["-map", "0:v", "-map", "[outa]"]
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
        cmd += [str(output)]

        self._run(cmd, f"sfx overlay seg {index}")
        return output

    def apply_transition(self, segment_path: Path, transition: str, index: int) -> Path:
        """Apply an entry transition (fade_in, flash_white) to a segment."""
        if transition in ("cut", "none"):
            return segment_path

        output = self.workspace / f"seg_{index:03d}_tr.mp4"

        if transition == "fade_in":
            vf = "fade=t=in:st=0:d=0.5"
            af = "afade=t=in:st=0:d=0.5"
        elif transition == "flash_white":
            vf = "fade=t=in:st=0:d=0.2:color=white"
            af = "afade=t=in:st=0:d=0.2"
        else:
            return segment_path

        cmd = ["ffmpeg", "-y", "-i", str(segment_path)]
        cmd += ["-vf", vf, "-af", af]
        cmd += self._encoder_args()
        cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [str(output)]

        self._run(cmd, f"transition seg {index}")
        return output

    def image_to_clip(self, image_path: Path, duration: float, label: str = "img") -> Path:
        """Convert a static image into a video clip with silent audio."""
        output = self.workspace / f"{label}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(image_path),
            "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
            "-t", f"{duration:.2f}",
            "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                   f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,"
                   f"fade=t=in:st=0:d=0.5,fade=t=out:st={duration-0.5:.2f}:d=0.5",
            "-shortest",
            "-pix_fmt", "yuv420p",
            "-r", str(int(self.fps)),
        ]
        cmd += self._encoder_args()
        cmd += ["-c:a", "aac", "-b:a", "192k", str(output)]
        self._run(cmd, f"image_to_clip {label}")
        return output

    def extract_random_frame(self, timestamp: float) -> Path:
        """Extract a single frame from the source video."""
        output = self.workspace / f"frame_{int(timestamp)}.jpg"
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", str(self.source),
            "-frames:v", "1", "-q:v", "2",
            str(output),
        ]
        self._run(cmd, f"extract frame @{timestamp:.1f}s")
        return output

    def concatenate(self, segment_paths: list[Path]) -> Path:
        """Concatenate segments using the concat demuxer."""
        concat_file = self.workspace / "concat_list.txt"
        with open(concat_file, "w") as f:
            for p in segment_paths:
                f.write(f"file '{p.resolve()}'\n")

        output = self.workspace / "final_edit.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output),
        ]
        self._run(cmd, "concatenate")
        return output

    def _render_one_segment(self, i: int, seg: dict) -> tuple[int, Path]:
        """Render a single segment (extract + sfx + transition). Thread-safe."""
        vfx = seg.get("video_effects", seg.get("video_effect", "none"))
        if self.perf and not {'fade_out', 'chromatic_aberration'}.intersection([vfx] if isinstance(vfx, str) else vfx):
            from perf.graph import Clip, render
            from perf.encoders import best, Encoder
            effects = [vfx] if isinstance(vfx, str) else vfx
            sfx = []
            for entry in seg.get('sound_effects', []):
                file = SOUND_EFFECTS.get(entry.get('sfx_key'), {}).get('file')
                if file and Path(file).is_file():
                    sfx.append(dict(file=file, offset=entry.get('offset_in_segment', 0)))
            clip = Clip(self.source, self.workspace / f'seg_{i:03d}.mp4',
                        seg['source_start'], seg['source_end'], self.width, self.height,
                        self.fps, seg.get('speed', 1), seg.get('transition_in', 'cut'))
            encoder = best(threads=2)
            try:
                path = render(clip, effects, sfx, encoder=encoder, cache=self.cache)
            except RuntimeError:
                if not encoder.hardware:
                    raise
                path = render(clip, effects, sfx, encoder=Encoder(), cache=self.cache)
            return i, path

        print(f"[render] Segment {i+1}: "
              f"{seg['source_start']:.1f}s-{seg['source_end']:.1f}s "
              f"effects={vfx} speed={seg.get('speed', 1.0)}x")

        path = self.extract_segment(
            index=i,
            start=seg["source_start"],
            end=seg["source_end"],
            video_effects=vfx,
            speed=seg.get("speed", 1.0),
        )
        path = self.overlay_sfx(path, seg.get("sound_effects", []), i)
        path = self.apply_transition(path, seg.get("transition_in", "cut"), i)
        return i, path

    def render(self, edit_plan: dict) -> Path:
        """Full render pipeline: extract → sfx → transitions → concat.

        Uses NVENC GPU for fast encoding. Segments processed sequentially
        to avoid NVENC session limits, but each segment encodes fast on GPU.
        """
        # Explicit opt-in keeps old planner payloads and defaults unchanged.
        if not isinstance(edit_plan, dict) or edit_plan.get("render_version") == 2:
            from render.engine import Renderer
            return Renderer(self).render(edit_plan)

        segments = edit_plan.get("segments", [])
        if not segments:
            raise ValueError("Edit plan has no segments")

        encoder = "NVENC" if HAS_NVENC else "libx264"
        print(f"[render] Using {encoder} encoder for {len(segments)} segments")

        if self.perf:
            from perf.parallel import render_all
            from perf.encoders import best
            rendered = render_all([lambda i=i, seg=seg: self._render_one_segment(i, seg)
                                   for i, seg in enumerate(segments)], best(threads=2))
            final_paths = [path for _, path in rendered]
        else:
            final_paths = [self._render_one_segment(i, seg)[1] for i, seg in enumerate(segments)]

        # Concatenate
        print(f"[render] Concatenating {len(final_paths)} segments...")
        return self.concatenate(final_paths)
