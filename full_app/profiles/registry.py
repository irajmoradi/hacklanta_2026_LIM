"""Profile schema, aspect-ratio transforms, and Unicode-aware OCR matching."""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c))))


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    anchor: str = "stretch"

    def __post_init__(self):
        if not (0 <= self.x1 < self.x2 <= 1 and 0 <= self.y1 < self.y2 <= 1):
            raise ValueError("Box must have positive area within normalized frame")
        if self.anchor not in {"stretch", "left", "center", "right"}:
            raise ValueError("Unknown horizontal HUD anchor")

    def pixels(self, width: int, height: int, *, letterboxed: bool = False):
        """Return a clamped, exclusive-right/bottom crop; baseline is 16:9.

        Native HUDs retain height-relative size and their horizontal anchor.
        letterboxed=True instead maps into a centered 16:9 content rectangle.
        """
        if width <= 0 or height <= 0:
            raise ValueError("Frame dimensions must be positive")
        if letterboxed:
            scale = min(width / 16, height / 9)
            w, h = 16 * scale, 9 * scale
            ox, oy = (width - w) / 2, (height - h) / 2
            coords = (ox + self.x1*w, oy + self.y1*h, ox + self.x2*w, oy + self.y2*h)
        else:
            w = width if self.anchor == "stretch" else height * 16 / 9
            ox = {"stretch": 0, "left": 0, "center": (width-w)/2, "right": width-w}[self.anchor]
            coords = (ox+self.x1*w, self.y1*height, ox+self.x2*w, self.y2*height)
        x1, y1, x2, y2 = coords
        left, top = max(0, min(width-1, math.floor(x1))), max(0, min(height-1, math.floor(y1)))
        return left, top, max(left+1, min(width, math.ceil(x2))), max(top+1, min(height, math.ceil(y2)))


@dataclass(frozen=True)
class GameProfile:
    name: str
    display_name: str
    regions: dict[str, Box]
    keywords: dict[str, tuple[str, ...]]
    detection_keywords: dict[str, tuple[str, ...]]
    alive_rules: tuple[str, ...]
    dead_rules: tuple[str, ...]
    spectating_rules: tuple[str, ...]
    highlights: tuple[str, ...]
    lowlights: tuple[str, ...]
    signal_weights: dict[str, float]
    aspect_notes: str

    def prompt_fragment(self) -> str:
        return (Path(__file__).resolve().parents[1] / "prompts" / "games" / f"{self.name}.txt").read_text(encoding="utf-8")


def list_profiles() -> tuple[str, ...]:
    return ("generic", "valorant", "overwatch2", "deadlock", "league_of_legends")


@lru_cache(maxsize=5)
def get_profile(name: str = "generic") -> GameProfile:
    if name not in list_profiles():
        raise ValueError(f"Unknown game profile: {name}")
    data = json.loads((Path(__file__).parent / "data" / f"{name}.json").read_text(encoding="utf-8"))
    data["regions"] = {k: Box(*v) for k, v in data["regions"].items()}
    for field in ("keywords", "detection_keywords"):
        data[field] = {k: tuple(v) for k, v in data[field].items()}
    for field in ("alive_rules", "dead_rules", "spectating_rules", "highlights", "lowlights"):
        data[field] = tuple(data[field])
    return GameProfile(**data)


def contains_phrase(text: str, phrase: str) -> bool:
    return f" {normalize(phrase)} " in f" {normalize(text)} "


def match_events(text: str, profile: str | GameProfile = "generic") -> set[str]:
    """Candidate events only: a feed mention does not establish player attribution."""
    p = get_profile(profile) if isinstance(profile, str) else profile
    return {event for event, phrases in p.keywords.items() if any(contains_phrase(text, phrase) for phrase in phrases)}
