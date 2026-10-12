"""JSON-safe audio evidence, using the EXT-01 Candidate envelope."""

from typing import Literal

from pydantic import BaseModel, Field


class Word(BaseModel):
    start: float
    end: float
    text: str
    probability: float = 1.0


class AudioEvent(BaseModel):
    start: float
    end: float
    type: Literal["laugh", "shout", "cheer", "gunfire", "hype_phrase", "silence"]
    score: float
    signals: dict[str, float] = Field(default_factory=dict)
    source: str
    text: str | None = None
    cue: str | None = None


class AudioSecond(BaseModel):
    start: float
    end: float
    score: float
    signals: dict[str, float]
    events: list[AudioEvent] = Field(default_factory=list)


class AudioSignals(BaseModel):
    duration: float
    sample_rate: int = 16000
    seconds: list[AudioSecond] = Field(default_factory=list)
    events: list[AudioEvent] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    backends: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
