"""Pydantic models for the pipeline data."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VideoMeta(BaseModel):
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str


class Clip(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    type: Literal["good", "bad"]
    description: str

    @model_validator(mode="after")
    def valid_timestamps(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.start != self.start_seconds or self.end != self.end_seconds:
            raise ValueError("timestamp aliases must match")
        return self


class SFXPlacement(BaseModel):
    sfx_key: str
    offset_in_segment: float = 0.0


class EditSegment(BaseModel):
    source_start: float
    source_end: float
    video_effects: list[str] = ["none"]
    speed: float = 1.0
    transition_in: str = "cut"
    sound_effects: list[SFXPlacement] = []


class EditPlan(BaseModel):
    segments: list[EditSegment]


class ClipList(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    clips: list[Clip]


class ScoringCandidate(BaseModel):
    """Input adapter for EXT-01 Candidate JSON, independent of optional signals."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    score: float
    signals: dict[str, float]
    events: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_window(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class WindowAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    player_alive: bool | None
    kind: Literal["highlight", "lowlight", "neutral"]
    hype: float = Field(ge=0, le=10)
    caption: str = Field(min_length=1, max_length=240, pattern=r"^[^\r\n]+$")
    reaction: Literal["sick_kill", "clutch", "bruh", "fail", "funny", "wholesome", "hype", "roast"]


class ScoredWindow(ScoringCandidate, WindowAssessment):
    """Candidate metadata plus a validated VLM assessment."""
