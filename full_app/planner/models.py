"""Local v2 render contract; all placement times are output-timeline seconds."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.effects import SOUND_EFFECTS, VIDEO_EFFECTS

Mode = Literal["nice", "mean"]
from render.contracts import Style, Aspect
ReactionLabel = Literal["sick_kill", "clutch", "bruh", "fail", "funny", "wholesome", "hype", "roast"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Signals(Model):
    """Event timestamps are absolute source seconds, not clip-relative offsets."""

    action_time: float | None = None
    kill_time: float | None = None
    fail_time: float | None = None
    clutch: bool = False
    multikill: bool = False
    kind: str = ""


class RankedClip(Model):
    id: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    score: float
    label: Literal["highlight", "lowlight"]
    caption: str = Field(default="", max_length=240)
    reaction_label: ReactionLabel | None = None
    signals: Signals = Field(default_factory=Signals)
    game_profile: str = "generic"

    @model_validator(mode="after")
    def source_bounds(self):
        if self.end <= self.start:
            raise ValueError("clip end must follow start")
        for time in (self.signals.action_time, self.signals.kill_time, self.signals.fail_time):
            if time is not None and not self.start <= time < self.end:
                raise ValueError("event timestamps must be inside the source clip")
        return self


class PlannerOptions(Model):
    mode: Mode = "nice"
    style: Style = "hype montage"
    target_length: float = Field(default=30, gt=0)
    aspect: Aspect = "16:9"
    min_clip_length: float = Field(default=1, gt=0)
    max_clip_length: float = Field(default=6, gt=0)

    @model_validator(mode="after")
    def feasible(self):
        if self.min_clip_length > min(3, self.max_clip_length, self.target_length):
            raise ValueError("minimum clip length must fit the hook, maximum, and budget")
        return self


class PlannedClip(Model):
    id: str
    source_id: str
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    start: float = Field(ge=0)
    duration: float = Field(gt=0)
    speed: Literal[0.5, 1.0] = 1.0
    phase: Literal["hook", "hook_climax", "build_up", "setup", "highlight", "fail", "climax"]
    score: float
    label: Literal["highlight", "lowlight"]
    similarity_key: str
    game_profile: str
    peak: float = Field(ge=0)


class Placement(Model):
    clip_id: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0)


class Effect(Placement):
    name: str


class Sound(Placement):
    name: str
    gain: float = Field(default=0.7, ge=0, le=1)


class Text(Placement):
    content: str = Field(min_length=1, max_length=240)
    role: Literal["caption", "meme", "outro"] = "caption"
    position: Literal["lower_safe", "center"] = "lower_safe"


class Transition(Placement):
    name: Literal["cut", "fade_in", "fade_out", "flash_white"]


class Reaction(Placement):
    label: ReactionLabel
    position: Literal["top_right", "bottom_right"]
    duck_game_audio: bool = True


class EnergyPoint(Model):
    time: float = Field(ge=0)
    energy: float = Field(ge=0, le=1)


class Music(Model):
    energy_curve: list[EnergyPoint] = Field(default_factory=list)
    duck_under: list[Literal["speech", "sfx", "reactions"]] = Field(
        default_factory=lambda: ["speech", "sfx", "reactions"]
    )
    # Intent only: the caller supplies a licensed music asset to the renderer.
    mood: str = ""


class RenderPlan(Model):
    version: Literal[2] = 2
    mode: Mode
    style: Style
    aspect: Aspect
    target_length: float = Field(gt=0)
    min_clip_length: float = Field(gt=0)
    max_clip_length: float = Field(gt=0)
    duration: float = Field(ge=0)
    clips: list[PlannedClip] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    sfx: list[Sound] = Field(default_factory=list)
    text: list[Text] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    reactions: list[Reaction] = Field(default_factory=list)
    music: Music = Field(default_factory=Music)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def timeline(self):
        eps = 1e-6
        by_id = {c.id: c for c in self.clips}
        if len(by_id) != len(self.clips):
            raise ValueError("duplicate timeline clip id")
        cursor = 0.0
        for c in self.clips:
            if abs(c.start - cursor) > eps:
                raise ValueError("clips must form a contiguous timeline")
            if not self.min_clip_length - eps <= c.duration <= self.max_clip_length + eps:
                raise ValueError("clip duration exceeds bounds")
            if c.source_end <= c.source_start or abs((c.source_end - c.source_start) / c.speed - c.duration) > eps:
                raise ValueError("source duration and playback speed disagree")
            cursor += c.duration
            if not c.start <= c.peak < cursor:
                raise ValueError("peak outside clip")
        if abs(cursor - self.duration) > eps or self.duration > self.target_length + eps:
            raise ValueError("invalid duration or exceeded budget")
        for group in (self.effects, self.sfx, self.text, self.transitions, self.reactions):
            for item in group:
                c = by_id.get(item.clip_id)
                if c is None or item.start < c.start - eps or item.start + item.duration > c.start + c.duration + eps:
                    raise ValueError("placement outside owning clip")
        if any(e.name not in VIDEO_EFFECTS or e.name == "none" for e in self.effects):
            raise ValueError("unknown video effect")
        if any(s.name not in SOUND_EFFECTS or s.name == "none" for s in self.sfx):
            raise ValueError("unknown sound effect")
        times = [p.time for p in self.music.energy_curve]
        if times != sorted(times) or any(t > self.duration + eps for t in times):
            raise ValueError("invalid music timeline")
        if self.clips:
            if self.clips[0].phase not in ("hook", "hook_climax") or self.clips[0].duration > 3 + eps:
                raise ValueError("first clip must be a hook of at most three seconds")
            if self.clips[-1].phase not in ("climax", "hook_climax"):
                raise ValueError("last clip must be the climax")
            if self.clips[0].source_id != self.clips[-1].source_id:
                raise ValueError("hook must tease the climax")
            for a, b, c in zip(self.clips, self.clips[1:], self.clips[2:]):
                if a.similarity_key == b.similarity_key == c.similarity_key:
                    raise ValueError("three similar consecutive clips")
        return self
