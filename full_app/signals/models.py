"""Public result schema and validated detector configuration."""

from dataclasses import asdict, dataclass, field
import math


WEIGHTS = {"scene": 0.15, "rms": 0.25, "onset": 0.15,
           "sustained": 0.15, "motion": 0.30, "ocr": 0.70}


@dataclass
class Candidate:
    start: float
    end: float
    score: float
    signals: dict[str, float]
    events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Config:
    sample_fps: float = 4.0
    width: int = 320
    threads: int = 4
    scene_backend: str = "auto"
    scene_threshold: float = 0.30
    ocr: bool = False
    ocr_width: int = 960
    ocr_regions: dict | None = None
    ocr_cooldown: float = 3.0
    weights: dict[str, float] = field(default_factory=lambda: WEIGHTS.copy())
    peak_threshold: float = 0.65
    pre_roll: float = 3.0
    post_roll: float = 4.0
    min_length: float = 3.0
    max_length: float = 20.0
    merge_gap: float = 1.0
    dead_motion: float = 0.008
    dead_audio: float = 0.012
    trim_dead_air: bool = True
    max_candidates: int = 30

    def __post_init__(self):
        for key in ("sample_fps", "width", "threads", "ocr_width", "min_length",
                    "max_length", "max_candidates"):
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and positive")
        for key in ("scene_threshold", "ocr_cooldown", "peak_threshold", "pre_roll",
                    "post_roll", "merge_gap", "dead_motion", "dead_audio"):
            value = getattr(self, key)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        for key in ("width", "threads", "ocr_width", "max_candidates"):
            if not isinstance(getattr(self, key), int):
                raise ValueError(f"{key} must be an integer")
        if not 2 <= self.sample_fps <= 4:
            raise ValueError("sample_fps must be between 2 and 4")
        if self.max_length < self.min_length:
            raise ValueError("max_length must be >= min_length")
        if self.scene_backend not in {"auto", "ffmpeg", "content", "adaptive"}:
            raise ValueError("unknown scene_backend")
        if set(self.weights) - set(WEIGHTS):
            raise ValueError("unknown signal weight")
        if any(not math.isfinite(v) or v < 0 for v in self.weights.values()):
            raise ValueError("weights must be finite and nonnegative")
        self.weights = {**WEIGHTS, **self.weights}
