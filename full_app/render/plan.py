"""Renderer input: source cuts in seconds; placements and tracks in output-local seconds."""

from typing import Literal
from .contracts import Preset
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
    duration: float | None = Field(default=None, gt=0)
    gain: float = Field(default=.7, ge=0, le=1)


class TimedEffect(Model):
    name: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0)


class TimedText(Model):
    start: float = Field(ge=0)
    duration: float = Field(gt=0)
    content: str = Field(max_length=240)
    position: Literal['lower_safe', 'center'] = 'lower_safe'


class TimedReaction(Model):
    start: float = Field(ge=0)
    duration: float = Field(gt=0)
    label: str
    position: Literal['top_right', 'bottom_right'] = 'bottom_right'
    duck_game_audio: bool = True


class Segment(Model):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    speed: float = Field(default=1, ge=.1, le=8)
    timed_effects: list[TimedEffect] = Field(default_factory=list, max_length=100)
    texts: list[TimedText] = Field(default_factory=list, max_length=100)
    reactions: list[TimedReaction] = Field(default_factory=list, max_length=100)
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
        # Playback speed is explicit; placement clocks are already output-local.
        from models.effects import VIDEO_EFFECTS
        for placement in [*self.timed_effects, *self.texts, *self.reactions]:
            if placement.start + placement.duration > self.duration + .001:
                raise ValueError('Placement exceeds segment duration')
        from models.effects import SOUND_EFFECTS
        for sound in self.sound_effects:
            if sound.sfx_key not in SOUND_EFFECTS or sound.sfx_key == 'none':
                raise ValueError('Unknown SFX')
            if sound.offset_in_segment >= self.duration or (sound.duration is not None and
                    sound.offset_in_segment+sound.duration > self.duration+.001):
                raise ValueError('Sound exceeds segment duration')
        for effect in self.timed_effects:
            if effect.name not in VIDEO_EFFECTS or effect.name in ('slow_motion', 'speed_2x'):
                raise ValueError('Timed speed effects must use segment speed')
        for effect in self.video_effects:
            if effect not in VIDEO_EFFECTS or effect in (
                "slow_motion", "speed_2x", "chromatic_aberration", "fade_out"
            ):
                raise ValueError(f"Unsupported v2 effect: {effect}")
        return self

    @property
    def duration(self):
        return (self.source_end - self.source_start) / self.speed


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
    chaos: float = Field(default=.35, ge=0, le=1)
    seed: int = 0
    render_version: Literal[2] = 2
    segments: list[Segment] = Field(min_length=1, max_length=100)
    preset: Preset = "landscape"
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
