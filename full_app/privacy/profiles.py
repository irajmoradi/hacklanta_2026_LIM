"""Conservative defaults for standard 16:9 HUDs, overridable by profile data."""
from .models import Box


def box(x, y, width, height):
    return Box(x=x, y=y, width=width, height=height)


COMMON = {
    "scoreboard": box(.15, .15, .70, .65),
    "nameplates": box(.1, .15, .8, .6),
    "party_voice": box(0, 0, .25, .35),
    "notifications": box(.65, .65, .35, .35),
    "discord": box(.65, 0, .35, .25),
    "webcam": box(0, .65, .25, .35),
}
DEFAULTS = {
    "valorant": {"kill_feed": box(.64, .03, .36, .27), "chat": box(0, .55, .4, .4)},
    "overwatch2": {"kill_feed": box(.64, .02, .36, .28), "chat": box(0, .55, .4, .4)},
    "deadlock": {"kill_feed": box(.62, .03, .38, .30), "chat": box(0, .55, .4, .4)},
    "league": {"kill_feed": box(.75, .15, .25, .45), "chat": box(0, .45, .4, .4)},
}


def regions_for(options):
    if options.regions is not None:
        return options.regions
    key = options.game.casefold().replace(" ", "").replace("_", "").replace("-", "")
    key = {"ow2": "overwatch2", "lol": "league", "leagueoflegends": "league"}.get(key, key)
    if key not in DEFAULTS:
        raise ValueError(f"unknown privacy profile: {options.game}")
    return {**COMMON, **DEFAULTS[key]}
