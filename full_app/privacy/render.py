"""FFmpeg privacy pass, applied before montage cuts, speed changes or reframing."""
import json
import math
from pathlib import Path
import subprocess
import tempfile

from .models import BlurTrack


def build_filtergraph(track):
    track = BlurTrack.model_validate(track)
    parts = ["[0:v]setpts=PTS-STARTPTS,format=yuv444p[p0]"]
    for i, box in enumerate(track.boxes):
        x, y = math.floor(box.x * track.width), math.floor(box.y * track.height)
        right = min(track.width, math.ceil((box.x+box.width)*track.width))
        bottom = min(track.height, math.ceil((box.y+box.height)*track.height))
        w, h = right-x, bottom-y
        # Tiny boxes still have a valid radius. At 1px, no meaningful blur exists.
        radius = min(20, w//2, h//2)
        parts.append(f"[p{i}]split=2[base{i}][crop{i}]")
        effect = f"boxblur=luma_radius={radius}:luma_power=3:chroma_radius={radius}:chroma_power=3"
        parts.append(f"[crop{i}]crop={w}:{h}:{x}:{y}:exact=1,{effect}[blur{i}]")
        parts.append(f"[base{i}][blur{i}]overlay={x}:{y}:format=yuv444:"
                     f"enable='gte(t,{box.start:.9f})*lt(t,{box.end:.9f})'[p{i+1}]")
    parts.append(f"[p{len(track.boxes)}]null[privacy]")
    return ";".join(parts)


def render_private_source(source, output, track):
    """Render a source-aligned blur track, retaining optional audio. No shell."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("privacy output must differ from source")
    track = BlurTrack.model_validate(track)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "json", str(source)],
                           capture_output=True, check=True, text=True, timeout=30)
    streams = json.loads(probe.stdout)["streams"]
    if not streams or (streams[0]["width"], streams[0]["height"]) != (track.width, track.height):
        raise ValueError("privacy track dimensions do not match source")
    # Script avoids platform command-length limits for long blur tracks.
    with tempfile.TemporaryDirectory(prefix="lim-privacy-") as tmp:
        script = Path(tmp) / "privacy.ffgraph"
        script.write_text(build_filtergraph(track), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source),
            "-filter_complex_threads", "1", "-filter_complex_script", str(script),
            "-map", "[privacy]", "-map", "0:a?", "-map_metadata", "-1",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-af", "asetpts=PTS-STARTPTS", "-c:a", "aac", str(output),
        ], capture_output=True, check=True, timeout=3600)
    return output
