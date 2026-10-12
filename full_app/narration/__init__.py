"""Opt-in caster scripts, peak-aware timing, and cached voiceover tracks."""

from dataclasses import dataclass, field
import math
from pathlib import Path
import tempfile

from . import providers


PERSONAS = {
    "hype_caster": "What a play!",
    "deadpan_roast": "Well. That happened.",
    "nature_documentary": "Observe the player in the wild.",
}


@dataclass(frozen=True)
class NarrationSegment:
    start: float
    end: float
    text: str
    audio_file: Path | None = None


@dataclass
class NarrationTrack:
    segments: list[NarrationSegment] = field(default_factory=list)
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)
    characters: int = 0


def _dict(value) -> dict:
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def _number(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Narration timestamps must be finite")
    return number


def _gaps(start, end, blocked):
    cursor = start
    for left, right in sorted(blocked):
        if right <= cursor or left >= end:
            continue
        if left > cursor:
            yield cursor, min(left, end)
        cursor = max(cursor, right)
    if cursor < end:
        yield cursor, end


def _words(text: str, limit: int) -> str:
    return " ".join(str(text).split()[:limit])


def build(clips, plan, persona="hype_caster", *, character_cap=1000,
          cache_dir=None, allow_network=False) -> NarrationTrack:
    """Build on montage seconds; see docs/narration.md for the timeline contract."""
    persona = persona.replace(" ", "_")
    if persona not in PERSONAS:
        raise ValueError("Unknown narration persona")
    if isinstance(character_cap, bool) or not isinstance(character_cap, int) or character_cap < 0:
        raise ValueError("character_cap must be a nonnegative integer")
    plan = _dict(plan)
    clips = [_dict(clip) for clip in clips]
    track = NarrationTrack()
    blocked = []
    for overlay in plan.get("reaction_overlays", []):
        left, right = _number(overlay["start"]), _number(overlay["end"])
        if left < 0 or right <= left:
            raise ValueError("Invalid reaction overlay interval")
        blocked.append((max(0, left - 0.1), right + 0.1))
    contexts, windows = [], []
    for raw in plan.get("segments", []):
        segment = _dict(raw)
        start, end = _number(segment["source_start"]), _number(segment["source_end"])
        speed = _number(segment.get("speed", 1))
        if start < 0 or end <= start or speed <= 0:
            raise ValueError("Invalid edit segment")
        # Legacy renderer applies speed effects in addition to segment.speed.
        for effect in segment.get("video_effects", []):
            speed *= {"slow_motion": 0.5, "speed_2x": 2}.get(effect, 1)
        length = (end - start) / speed
        offset = track.duration
        track.duration += length
        matches = [c for c in clips if _number(c.get("start", c.get("start_seconds", 0))) < end
                   and _number(c.get("end", c.get("end_seconds", 0))) > start]
        # Ranked input order is authoritative when several clips overlap.
        clip = matches[0] if matches else {}
        peak = _number(clip.get("peak_time", (start + end) / 2))
        peak = offset + min(length, max(0, (peak - start) / speed))
        gaps = list(_gaps(offset, track.duration, blocked))
        gaps = [(a, b) for a, b in gaps if b - a >= 1.0]
        if not gaps:
            continue
        left, right = min(gaps, key=lambda gap: (max(gap[0] - peak, peak - gap[1], 0), -(gap[1]-gap[0])))
        max_words = min(18, int((right - left) * 2))
        caption = clip.get("caption") or clip.get("description") or "The next play unfolds."
        contexts.append({"caption": _words(caption, 40), "max_words": max_words})
        windows.append((left, right, peak))
    if character_cap == 0 or not contexts:
        return track
    lines = [_words(PERSONAS[persona] + " " + c["caption"], c["max_words"]) for c in contexts]
    if allow_network:
        try:
            generated = providers.gemini_script(contexts, persona)
            if generated is not None:
                lines = [_words(line, c["max_words"]) for line, c in zip(generated, contexts)]
        except Exception:
            track.warnings.append("Script provider unavailable; using deterministic templates.")
    voice = providers.voice_id()
    cache_dir = cache_dir or Path(tempfile.gettempdir()) / "lim-narration-cache"
    for text, (left, right, peak) in zip(lines, windows):
        remaining = character_cap - track.characters
        if len(text) > remaining:
            # Never cut a word to meet the job budget.
            words = text.split()
            while words and len(" ".join(words)) > remaining:
                words.pop()
            text = " ".join(words)
        if not text:
            continue
        track.characters += len(text)  # Charge attempts too, including failed requests.
        audio = None
        duration = max(0.5, len(text.split()) / 2)
        try:
            audio = providers.synthesize(text, voice, cache_dir, allow_network=allow_network)
            if audio is not None:
                duration = providers.wav_duration(audio)
        except Exception:
            track.warnings.append("Speech provider unavailable; retaining script only.")
            audio = None
        if duration > right - left:
            track.warnings.append("Speech exceeds its safe gap; omitted to protect reactions.")
            continue
        begin = min(max(left, peak - duration / 2), right - duration)
        track.segments.append(NarrationSegment(begin, begin + duration, text, audio))
    return track


from .render import filter_graph, render  # noqa: E402

__all__ = ["build", "NarrationTrack", "NarrationSegment", "filter_graph", "render"]
