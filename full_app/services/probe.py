"""FFprobe wrapper — extract video metadata."""

import json
import subprocess
from pathlib import Path


def probe_video(path: str | Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = next(
        s for s in data["streams"] if s["codec_type"] == "video"
    )
    audio_stream = next(
        (s for s in data["streams"] if s["codec_type"] == "audio"),
        None,
    )

    # Parse frame rate like "60/1" or "30000/1001"
    fps_parts = video_stream["r_frame_rate"].split("/")
    fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])

    return {
        "duration": float(data["format"]["duration"]),
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "fps": round(fps, 2),
        "video_codec": video_stream["codec_name"],
        "audio_codec": audio_stream["codec_name"] if audio_stream else "none",
    }
