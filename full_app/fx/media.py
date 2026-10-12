"""Raw FFprobe metadata shared by the optional media renderers."""

import json
from pathlib import Path
import subprocess
from typing import Any


def probe(path: str | Path, *, timeout: float | None = None) -> dict[str, Any]:
    """Keep stream metadata intact, including audio-only files and still images."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=timeout,
    )
    return json.loads(result.stdout)
