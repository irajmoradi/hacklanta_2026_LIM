"""Versioned JSON manifest, with video paths relative to the manifest."""

import json
from pathlib import Path

from .metrics import interval, number


def load_dataset(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("videos"), list) or not data["videos"]:
        raise ValueError("Expected version=1 and a nonempty videos list")
    records, ids = [], set()
    for raw in data["videos"]:
        identity = raw["id"]
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Video IDs must be unique nonempty strings")
        ids.add(identity)
        duration = number(raw["duration_seconds"], "duration", 0)
        if not duration:
            raise ValueError("duration must be positive")
        video = (path.parent / raw["path"]).resolve()
        if not video.is_file():
            raise FileNotFoundError(video)
        highlights = [interval(item, duration) for item in raw["highlights"]]
        records.append({"id": identity, "path": video, "duration_seconds": duration,
                        "highlights": highlights})
    return records
