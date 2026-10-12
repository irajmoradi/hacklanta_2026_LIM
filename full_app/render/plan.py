"""Planner-facing schema. All timestamps are seconds; tracks are clip-local."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TrackPoint(Model):
    time: float = Field(ge=0)
    x: float = Field(ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)


class SubjectMetadata(Model):
    subject_track: list[TrackPoint] = Field(default_factory=list, max_length=500)


class Word(Model):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(max_length=200)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Word end must follow start")
        return self


class Sound(Model):
    sfx_key: str
    offset_in_segment: float = Field(default=0, ge=0)


class Segment(Model):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    video_effects: list[str] = Field(default_factory=list)
    sound_effects: list[Sound] = Field(default_factory=list)
    title: str | None = Field(default=None, max_length=200)
    sam: SubjectMetadata | None = None
    words: list[Word] = Field(default_factory=list)
    fx: list[dict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def ordered(self):
        if self.source_end <= self.source_start:
            raise ValueError("Segment end must follow start")
        if self.fx:
            from fx import REGISTRY, Timing
            for entry in self.fx:
                effect = REGISTRY[entry['name']]
                timing = Timing(self.duration, entry['start'], entry['end'])
                effect.values(entry.get('params', {}))
                if effect.changes_duration:
                    raise ValueError('Time-changing FX require a prepared source timeline')
        if self.sam:
            times = [p.time for p in self.sam.subject_track]
            if any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError("Track times must be strictly increasing")
        # Speed effects change the timeline; use explicit source cuts in v2.
        from models.effects import VIDEO_EFFECTS
        for effect in self.video_effects:
            if effect not in VIDEO_EFFECTS or effect in (
                "slow_motion", "speed_2x", "chromatic_aberration", "fade_out"
            ):
                raise ValueError(f"Unsupported v2 effect: {effect}")
        return self

    @property
    def duration(self):
        return self.source_end - self.source_start


class Captions(Model):
    enabled: bool = False
    transcribe: bool = False
    model: str = "tiny"
    mask_profanity: bool = False
    profanity: list[str] = Field(default_factory=lambda: ["fuck", "shit", "bitch", "asshole"])


class Music(Model):
    path: str
    volume: float = Field(default=0.18, ge=0, le=1)
    beat_sync: bool = False
    beats: list[float] | None = None
    snap_tolerance: float = Field(default=0.25, ge=0, le=1)
    duck: bool = True

    @model_validator(mode="after")
    def ordered(self):
        if self.beats is not None and (any(t < 0 for t in self.beats) or
                any(b <= a for a, b in zip(self.beats, self.beats[1:]))):
            raise ValueError("Beats must be nonnegative and strictly increasing")
        return self


class Card(Model):
    text: str = Field(min_length=1, max_length=200)
    duration: float = Field(default=1.5, ge=0.25, le=15)


class RenderPlan(Model):
    render_version: Literal[2] = 2
    segments: list[Segment] = Field(min_length=1, max_length=100)
    preset: Literal["landscape", "vertical", "square"] = "landscape"
    resolution: Literal[720, 1080] = 1080
    fps: int = Field(default=30, ge=10, le=60)
    reframe: Literal["crosshair", "motion", "blur"] = "crosshair"
    captions: Captions = Field(default_factory=Captions)
    music: Music | None = None
    transition: Literal["cut", "fast_zoom", "whip", "flash", "glitch"] = "cut"
    transition_duration: float = Field(default=0.15, ge=0.05, le=1)
    intro: Card | None = None
    outro: Card | None = None

    @property
    def size(self):
        short = self.resolution
        long = short * 16 // 9
        return {"landscape": (long, short), "vertical": (short, long),
                "square": (short, short)}[self.preset]
