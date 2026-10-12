"""Public, renderer-independent music metadata (all times are seconds)."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Section:
    name: str
    start: float
    end: float


@dataclass(frozen=True)
class MusicBed:
    path: Path
    bpm: float
    beats: list[float]
    sections: list[Section]
    source: str = "procedural"
    license: str | None = None
    attribution: str | None = None


@dataclass(frozen=True)
class TrackAnalysis:
    bpm: float | None
    energy: float
    duration: float
    method: str


def timeline(length: float, climax_at: float, bpm: float):
    """Anchor the beat grid to the drop, even for a non-beat-aligned climax."""
    import math

    period = 60.0 / bpm
    first = math.ceil(-climax_at / period)
    last = math.ceil((length - climax_at) / period)
    beats = [climax_at + i * period for i in range(first, last)]
    outro = max(climax_at, length - min(4 * period, (length - climax_at) / 3))
    sections = [Section("intro", 0.0, climax_at),
                Section("drop", climax_at, outro), Section("outro", outro, length)]
    return beats, sections
