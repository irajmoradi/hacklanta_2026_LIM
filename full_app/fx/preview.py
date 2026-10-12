"""Bounded, shell-free preview rendering and an opt-in external RIFE adapter."""

from pathlib import Path
import subprocess
import warnings
from typing import Callable

from . import Effect, Timing
from .media import probe as probe_media


def run(args: list) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-3000:]}")
    return result


def probe(source: str | Path) -> dict:
    try:
        return probe_media(source, timeout=180)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed ({exc.returncode}): {exc.stderr[-3000:]}") from exc


def render_preview(source, output, effect: Effect, timing: Timing, *,
                   rife_hook: Callable[[Path, Path, float], None] | None = None, **params) -> Path:
    """Video-only preview. A trusted RIFE hook may replace the encoded preview.

    Hook(source_preview, candidate_path, fps) must retain geometry and duration.
    Missing/failed optional hooks fall back to the FFmpeg preview without ML imports.
    """
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("Preview output must differ from source")
    chain = effect.filter(timing, **params)
    duration = effect.output_duration(timing, **params)
    output.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
         "-filter_threads", "1", "-vf", f"trim=duration={timing.duration},setpts=PTS-STARTPTS,{chain},format=yuv420p",
         "-an", "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "18",
         "-r", timing.fps, "-t", duration, "-movflags", "+faststart", output])
    if rife_hook is not None:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="fx-rife-", dir=output.parent) as folder:
            candidate = Path(folder) / "interpolated.mp4"
            try:
                rife_hook(output, candidate, timing.fps)
                original = next(s for s in probe(output)["streams"] if s["codec_type"] == "video")
                updated = next(s for s in probe(candidate)["streams"] if s["codec_type"] == "video")
                if (original["width"], original["height"]) != (updated["width"], updated["height"]):
                    raise ValueError("RIFE hook changed geometry")
                if abs(float(updated["duration"]) - duration) > 2 / timing.fps:
                    raise ValueError("RIFE hook changed duration")
                candidate.replace(output)
            except Exception as exc:
                warnings.warn(f"Optional RIFE hook unavailable; retaining FFmpeg preview: {exc}", RuntimeWarning)
    return output
