"""Validated local library manifests and deterministic style/mode selection."""

from collections.abc import Iterable
from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class LibraryTrack:
    path: Path
    energy: float
    mood: tuple[str, ...]
    bpm: float | None
    license: str
    styles: tuple[str, ...]
    modes: tuple[str, ...]
    drop_at: float
    attribution: str | None


def number(value: float, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _tags(value, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{name} must be a list of nonempty strings")
    return tuple(v.strip().lower() for v in value)


def load_manifest(path: str | Path) -> list[LibraryTrack]:
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("tracks"), list):
        raise ValueError("Music manifest requires version 1 and a tracks list")
    tracks = []
    for entry in data["tracks"]:
        if not isinstance(entry, dict):
            raise ValueError("Music track must be an object")
        for key in ("path", "license"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"Track requires a nonempty {key}")
        track_path = (path.parent / entry["path"]).resolve()
        if not track_path.is_file():
            raise ValueError(f"Music file does not exist: {entry['path']}")
        bpm = entry.get("bpm")
        if bpm is not None:
            bpm = number(bpm, "bpm", 40, 240)
        attribution = entry.get("attribution")
        if attribution is not None and not isinstance(attribution, str):
            raise ValueError("attribution must be a string")
        tracks.append(LibraryTrack(
            track_path, number(entry.get("energy"), "energy", 0, 1),
            _tags(entry.get("mood"), "mood"), bpm, entry["license"].strip(),
            _tags(entry.get("styles", []), "styles"), _tags(entry.get("modes", []), "modes"),
            number(entry.get("drop_at", 0), "drop_at", 0, 599.999), attribution,
        ))
    return tracks


def select_track(tracks: Iterable[LibraryTrack], style: str, mode: str | None = None) -> LibraryTrack | None:
    target = .85 if style == "energetic" else .30
    moods = {"energetic", "hype", "intense"} if style == "energetic" else {"chill", "calm", "relaxed"}
    candidates = [track for track in tracks
                  if (not track.styles or style in track.styles)
                  and (mode is None or not track.modes or mode in track.modes)]
    if not candidates:
        return None
    return min(candidates, key=lambda track: (
        abs(track.energy - target) + (0 if moods.intersection(track.mood) else .25),
        str(track.path),
    ))
