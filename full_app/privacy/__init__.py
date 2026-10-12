"""Opt-in local privacy API; import does not load OCR models or call services."""
from .detector import detect_video
from .models import Box, BlurBox, BlurTrack, PrivacyOptions
from .render import build_filtergraph, render_private_source


def sanitize(source, output, payload=None):
    """Validate an API payload, detect regions and return (output_path, track)."""
    track = detect_video(source, payload)
    return render_private_source(source, output, track), track


def render_montage(runner, edit_plan, payload=None):
    """Opt-in adapter for the existing FFmpegRunner, for either render version.

    Sanitizing before edits keeps boxes aligned through cuts, speeds, and crops.
    The original runner/source is never modified.
    """
    from pathlib import Path
    import tempfile
    from services.ffmpeg_runner import FFmpegRunner

    with tempfile.TemporaryDirectory(prefix="privacy-", dir=runner.workspace) as tmp:
        source, track = sanitize(runner.source, Path(tmp) / "source.mp4", payload)
        private_runner = FFmpegRunner(runner.workspace, source, runner.width, runner.height, runner.fps)
        return private_runner.render(edit_plan), track


__all__ = ["Box", "BlurBox", "BlurTrack", "PrivacyOptions", "detect_video",
           "build_filtergraph", "render_private_source", "sanitize", "render_montage"]
