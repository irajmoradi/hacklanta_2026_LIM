"""Public ingest results; all timestamps are seconds on the prepared timeline."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

Progress = Callable[[dict], None]


class IngestError(ValueError):
    """Invalid input, exceeded limits, or failed media preparation."""


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 20 * 1024**3
    max_duration: float = 12 * 3600

    def __post_init__(self):
        import math

        if (not isinstance(self.max_bytes, int) or self.max_bytes <= 0
                or not math.isfinite(self.max_duration) or self.max_duration <= 0):
            raise IngestError("max_bytes must be a positive integer; max_duration must be positive and finite")


@dataclass(frozen=True)
class Chunk:
    path: Path
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def global_timestamp(self, local_seconds: float) -> float:
        if not 0 <= local_seconds <= self.duration:
            raise IngestError("Chunk timestamp is outside the chunk")
        return self.start + local_seconds


@dataclass(frozen=True)
class PreparedVideo:
    path: Path
    proxy: Path
    duration: float
    fps: float
    chunks: list[Chunk]
    chat_signal: list[dict] | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["path"], data["proxy"] = str(self.path), str(self.proxy)
        for chunk in data["chunks"]:
            chunk["path"] = str(chunk["path"])
        return data
