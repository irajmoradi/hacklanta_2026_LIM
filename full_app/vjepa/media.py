"""Shared raw ffprobe access; callers retain their own stream and duration rules."""

import json
from pathlib import Path
import subprocess


def probe_media(path: str | Path, *, entries: str | None = None,
                select_streams: str | None = None, timeout: float | None = None) -> dict:
    command = ["ffprobe", "-v", "error", "-of", "json"]
    command += ["-show_entries", entries] if entries else ["-show_streams", "-show_format"]
    if select_streams:
        command += ["-select_streams", select_streams]
    result = subprocess.run(command + [str(path)], capture_output=True, text=True,
                            check=True, timeout=timeout)
    return json.loads(result.stdout)
