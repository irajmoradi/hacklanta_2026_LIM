"""Pure aggregation of analyzed job snapshots; no inference or network calls."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def identity(value):
    return value.strip() if isinstance(value, str) else ""


def timestamp(value):
    """Epoch seconds or an ISO timestamp; naive ISO timestamps mean UTC."""
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            numeric = number(value)
            if numeric is None:
                raise ValueError("invalid timestamp")
            parsed = datetime.fromtimestamp(numeric, timezone.utc)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        raise ValueError("invalid timestamp") from None


def week_start(value):
    day = timestamp(value).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def records(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def mapping(value):
    return value if isinstance(value, dict) else {}


def _events(job, player, duration):
    sources = records(job.get("ocr_events"))
    for candidate in records(job.get("candidates")) + records(job.get("window_scores")):
        sources += records(candidate.get("events"))
    seen, result = set(), []
    for event in sources:
        time = number(event.get("time"))
        kind = event.get("type")
        if kind not in ("kill", "death") or time is None or not 0 <= time < duration:
            continue
        # Named actors take precedence; never assign another player's feed entry
        # to the POV owner merely because it appeared in their recording.
        actor = identity(event.get("player_id"))
        if not actor and (identity(event.get("killer")) or identity(event.get("victim"))):
            if identity(event.get("victim")) == player:
                actor, kind = player, "death"
            elif identity(event.get("killer")) == player:
                actor, kind = player, "kill"
            else:
                continue
        if actor != player and not (not actor and event.get("pov") is True):
            continue
        if event.get("region", "kill_feed") != "kill_feed":
            continue
        event_id = identity(event.get("id"))
        key = ("id", event_id) if event_id else (
            kind, time, identity(event.get("text")).casefold(),
            identity(event.get("killer")), identity(event.get("victim")))
        if key not in seen:
            seen.add(key)
            result.append({"time": time, "type": kind})
    return sorted(result, key=lambda e: (e["time"], e["type"]))


def _plays(job, player, duration, week):
    # Merge identical ranges, preferring scored windows over clips over raw
    # candidates. Signal z-scores are not calibrated hype scores.
    ranges = {}
    for source in ("candidates", "clips", "window_scores"):
        for clip in records(job.get(source)):
            start = number(clip.get("start", clip.get("start_seconds")))
            end = number(clip.get("end", clip.get("end_seconds")))
            if start is None or end is None or not 0 <= start < end <= duration:
                continue
            key = (start, end)
            ranges[key] = {**ranges.get(key, {}), **clip}
    result = []
    for (start, end), clip in sorted(ranges.items()):
        hype = number(clip.get("hype"))
        hype = hype if hype is not None and 0 <= hype <= 10 else None
        fail = clip.get("kind") == "lowlight" or clip.get("type") == "bad" or clip.get("reaction") in ("fail", "roast", "bruh")
        payload = json.dumps([job["id"], start, end], separators=(",", ":"))
        result.append({"clip_id": hashlib.sha256(payload.encode()).hexdigest(),
                       "job_id": job["id"], "player_id": player, "week": week,
                       "start": start, "end": end, "hype": hype, "is_fail": fail,
                       "description": identity(clip.get("caption") or clip.get("description"))[:500]})
    return result


def normalize_jobs(jobs):
    """Skip incomplete/unattributed snapshots, deduplicate job IDs (last wins)."""
    unique = {j["id"]: j for j in jobs if isinstance(j, dict) and identity(j.get("id"))}
    result = []
    for job in unique.values():
        player = identity(job.get("player_id"))
        analyzed = isinstance(job.get("clips"), list) or "analyze" in (job.get("completed") or [])
        if not player or not analyzed:
            continue
        duration = number(mapping(job.get("meta")).get("duration", job.get("duration")))
        if duration is None or duration <= 0:
            continue
        try:
            when = timestamp(job.get("recorded_at", job.get("created_at")))
        except ValueError:
            continue
        week = week_start(when)
        profile = job.get("game_profile") or mapping(job.get("options")).get("game_profile")
        game = identity(mapping(profile).get("name")) if isinstance(profile, dict) else identity(profile)
        # Character must describe the POV player, never the profile's roster.
        character = next((identity(job.get(k)) for k in ("character", "agent", "hero", "champion") if identity(job.get(k))), "")
        result.append({"job_id": job["id"], "player_id": player, "week": week,
                       "recorded_at": when.isoformat(), "duration": duration,
                       "game": game or "unknown", "character": character or None,
                       "events": _events(job, player, duration),
                       "plays": _plays(job, player, duration, week)})
    return sorted(result, key=lambda j: (j["recorded_at"], j["job_id"]))


def play_order(play):
    return (-(play["hype"] if play["hype"] is not None else -1), play["clip_id"])


def _summary(jobs):
    kills = deaths = 0
    multikills = Counter()
    characters = Counter()
    for job in jobs:
        events = job["events"]
        kills += sum(e["type"] == "kill" for e in events)
        deaths += sum(e["type"] == "death" for e in events)
        # Maximal chains of kills within five seconds; a death breaks a chain.
        chain, last = 0, None
        for event in events + [{"type": "death", "time": float("inf")}]:
            if event["type"] == "death" or (last is not None and event["time"] - last > 5):
                if chain >= 2:
                    multikills[str(chain)] += 1
                chain = 0
            if event["type"] == "kill":
                chain += 1
                last = event["time"]
            else:
                last = None
        if job["character"]:
            characters[(job["game"], job["character"])] += 1
    seconds = sum(j["duration"] for j in jobs)
    plays = sorted((p for j in jobs for p in j["plays"]), key=play_order)
    usage = [{"game": game, "character": char, "jobs": count}
             for (game, char), count in sorted(characters.items(), key=lambda x: (-x[1], x[0]))]
    return {"jobs": len(jobs), "duration_seconds": seconds, "kills": kills, "deaths": deaths,
            "kills_per_hour": round(kills * 3600 / seconds, 4) if seconds else None,
            "deaths_per_hour": round(deaths * 3600 / seconds, 4) if seconds else None,
            "multikill_counts": dict(sorted(multikills.items(), key=lambda x: int(x[0]))),
            "multikills": sum(multikills.values()), "character_usage": usage,
            "most_common_character": usage[0] if usage else None,
            "best_plays": [p for p in plays if not p["is_fail"]][:10],
            "roast_worthy_fails": [p for p in plays if p["is_fail"]][:10]}


def aggregate_players(jobs, week=None):
    """Aggregate raw job dictionaries into all-time totals and UTC weekly buckets."""
    players = defaultdict(list)
    for job in normalize_jobs(jobs):
        if week is None or job["week"] == week:
            players[job["player_id"]].append(job)
    result = []
    for player, owned in sorted(players.items()):
        weeks = defaultdict(list)
        for job in owned:
            weeks[job["week"]].append(job)
        result.append({"player_id": player, **_summary(owned),
                       "weeks": [{"week": w, **_summary(items)} for w, items in sorted(weeks.items())]})
    return result
