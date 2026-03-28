"""Pydantic models for the pipeline data."""

from typing import Literal

from pydantic import BaseModel


class VideoMeta(BaseModel):
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str


class Clip(BaseModel):
    start: float
    end: float
    start_seconds: float
    end_seconds: float
    type: Literal["good", "bad"]
    description: str


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
    clips: list[Clip]
