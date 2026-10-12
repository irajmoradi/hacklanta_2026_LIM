"""Deterministic, duration-preserving roast specs on a clip-local timeline."""

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Callable

from .safety import safe_line

TEMPLATES = ("top_bottom", "two_panel", "wasted", "stat_card")
LINES = {
    "whiff": ("Aim is still loading.", "Crosshair went on vacation.", "Aim discovered every wall."),
    "death": ("Respawn is the backup plan.", "Respawn express delivery.", "Respawn speedrun unlocked."),
    "fall": ("Landing was ambitious.", "Jump took the scenic route.", "Jump failed. Gravity undefeated."),
    "reload": ("Reload timing needs practice.", "Ammo is on vacation.", "Reload timing was spectacularly late."),
    "fail": ("Timing was almost perfect.", "Timing took a vacation.", "Timing unlocked maximum failure."),
}


@dataclass(frozen=True)
class FailMoment:
    time: float
    kind: str = "fail"

    def __post_init__(self):
        if isinstance(self.time, bool) or not isinstance(self.time, (int, float)) or not math.isfinite(self.time) or self.time < 0:
            raise ValueError("Fail time must be finite and nonnegative")
        if self.kind not in LINES:
            raise ValueError(f"Unknown fail kind: {self.kind}")


@dataclass(frozen=True)
class Overlay:
    template: str
    start: float
    end: float
    caption: str
    source: str
    kind: str


@dataclass(frozen=True)
class Beat:
    start: float
    end: float
    zoom: float


@dataclass(frozen=True)
class Sound:
    sfx_key: str
    offset_in_segment: float


@dataclass(frozen=True)
class RoastPlan:
    duration: float
    fps: float
    intensity: int
    overlays: tuple[Overlay, ...] = ()
    beats: tuple[Beat, ...] = ()
    sound_effects: tuple[Sound, ...] = ()

    def to_dict(self):
        """JSON-serializable spec; sound_effects matches FFmpegRunner.overlay_sfx."""
        return asdict(self)


def _sound_key():
    from models.effects import SOUND_EFFECTS
    root = Path(__file__).resolve().parents[1]
    for key in ("record_scratch", "spongebob_fail"):
        path = SOUND_EFFECTS.get(key, {}).get("file")
        if path and (root / path).is_file():
            return key
    return None


def plan_roasts(fails: list[FailMoment], duration: float, *, fps: float = 30,
                intensity: int = 1, template: str | None = None,
                line_writer: Callable | None = None) -> RoastPlan:
    """Plan one overlay per distinct fail frame, with at most one provider call.

    intensity: 0 off, 1 gentle, 2 spicy, 3 extra. Fail times must already reflect
    trim/speed edits. Freezes replace motion without extending the clip or audio.
    """
    if type(intensity) is not int or intensity not in range(4):
        raise ValueError("intensity must be an integer from 0 to 3")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (duration, fps)) or duration <= 0 or not 1 <= fps <= 240:
        raise ValueError("Require positive duration and fps in [1, 240]")
    if template is not None and template not in TEMPLATES:
        raise ValueError("Unknown template")
    if any(not isinstance(f, FailMoment) or f.time >= duration for f in fails):
        raise ValueError("Fails must be FailMoment instances inside the clip")
    ordered = sorted(fails, key=lambda f: (f.time, f.kind))
    unique = {}
    for fail in ordered:
        unique.setdefault(math.floor(fail.time * fps), fail)
    events = list(unique.values())
    if not intensity or not events:
        return RoastPlan(duration, fps, intensity)
    generated = []
    if line_writer is not None:
        try:
            result = line_writer([f.kind for f in events], intensity)
            if isinstance(result, list) and len(result) == len(events):
                generated = result
        except Exception:
            # Offline, refusal, malformed JSON, timeout: all use deterministic lines.
            pass
    overlays, beats, sounds = [], [], []
    sfx = _sound_key() if intensity >= 2 else None
    for i, fail in enumerate(events):
        start = math.floor(fail.time * fps) / fps
        next_start = math.floor(events[i + 1].time * fps) / fps if i + 1 < len(events) else duration
        end = min(duration, next_start, start + 2.4)
        caption = LINES[fail.kind][intensity - 1]
        origin = "fallback"
        if generated and safe_line(generated[i]):
            caption, origin = generated[i], "gemini"
        overlays.append(Overlay(template or TEMPLATES[i % len(TEMPLATES)], start, end, caption, origin, fail.kind))
        beats.append(Beat(start, min(end, start + (0.3, 0.5, 0.7)[intensity - 1]),
                          (1.08, 1.18, 1.28)[intensity - 1]))
        if sfx:
            sounds.append(Sound(sfx, start))
    return RoastPlan(duration, fps, intensity, tuple(overlays), tuple(beats), tuple(sounds))
