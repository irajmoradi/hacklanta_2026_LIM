"""Public, immutable multi-POV timeline records (seconds throughout)."""
from dataclasses import dataclass
from pathlib import Path
import math


@dataclass(frozen=True)
class Video:
    path: Path | str
    player: str = ""

    def __post_init__(self):
        object.__setattr__(self, "path", Path(self.path).resolve())
        object.__setattr__(self, "player", self.player or self.path.stem)
        if not isinstance(self.player, str) or any(c in self.player for c in "\r\n\x00"):
            raise ValueError("player must be a single line of text")


def normalize(videos):
    result = tuple(v if isinstance(v, Video) else Video(v) for v in videos)
    if not result or len({v.path for v in result}) != len(result):
        raise ValueError("provide at least one recording, with no duplicate paths")
    return result


@dataclass(frozen=True)
class Alignment:
    """match_time = offset + rate * local_time; first POV is the reference."""
    offset: float
    rate: float = 1.0
    confidence: float = 1.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.offset, self.rate, self.confidence)):
            raise ValueError("alignment values must be finite")
        if not .98 <= self.rate <= 1.02 or not 0 <= self.confidence <= 1:
            raise ValueError("rate must be within 2% of real time; confidence must be 0..1")

    def to_match(self, seconds):
        return self.offset + self.rate * seconds

    def to_local(self, seconds):
        return (seconds - self.offset) / self.rate


@dataclass(frozen=True)
class Angle:
    video_index: int
    start: float
    end: float
    score: float
    player: str


@dataclass(frozen=True)
class TeamCandidate:
    start: float
    end: float
    angles: tuple[Angle, ...]  # descending signals score; first is best

    @property
    def best(self):
        return self.angles[0]
