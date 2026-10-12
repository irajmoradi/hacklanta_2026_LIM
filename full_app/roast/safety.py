"""Fail-closed caption language: gameplay subjects, no arbitrary personal text.

An allowlist is intentional: an ever-growing slur denylist cannot protect against
obfuscation or novel identity attacks. Unknown words trigger a curated fallback.
"""

import re

SUBJECTS = {"aim", "crosshair", "shot", "reload", "respawn", "jump", "landing", "timing", "ammo", "grenade"}
WORDS = SUBJECTS | set("the that this a an is was has went took still just really very "
    "on off to for of with in at and but not no yes into out again "
    "missed missing target targets wall walls every floor sky orbit vacation holiday "
    "loading buffering practicing optional ambitious close almost nowhere "
    "left right up down delivered delivery express speedrun tutorial "
    "confidence accuracy damage style points zero maximum minimum "
    "scheduled unscheduled scenic route gravity won wins undefeated "
    "empty full critical success failure plan backup destination air "
    "found discovered unlocked achievement impressive cancelled delayed "
    "connection disconnected overshot undershot reloading sightseeing "
    "perfect perfectly terrible spectacular spectacularly needs more less "
    "practice missed landed failed early late too soon working overtime".split())


def safe_line(value: object) -> bool:
    """Accept short ASCII gameplay captions only; reject controls and obfuscation.

    Never normalize away suspicious characters or interpolate player metadata.
    This deliberately sacrifices open-ended prose for a narrow safe language.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return False
    if not re.fullmatch(r"[A-Za-z]+(?:[ A-Za-z.!?%-]*[A-Za-z.!?%])?", value):
        return False
    words = re.findall(r"[a-z]+", value.lower())
    subject = words[1] if len(words) > 1 and words[0] in {"the", "this", "that"} else words[0]
    return subject in SUBJECTS and all(word in WORDS for word in words)
