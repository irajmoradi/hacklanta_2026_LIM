"""Offline Twitch replay aggregation; optional network adapter is lazy-loaded."""

import json
import math
from pathlib import Path
import re

from .models import IngestError

EMOTES = re.compile(r"\b(?:PogChamp|Pog|PogU|Poggers|LUL|LULW|KEKW|OMEGALUL|PepeLaugh|Kappa|monkaS)\b", re.I)
CLIP_IT = re.compile(r"\bclip\s*(?:it|that|this)\b", re.I)


def _messages(source):
    if isinstance(source, (str, Path)):
        with Path(source).open(encoding="utf-8-sig") as handle:
            source = json.load(handle)
    if isinstance(source, dict):
        source = source.get("comments", source.get("messages"))
        if source is None:
            raise IngestError("Chat JSON must contain comments or messages")
    try:
        return iter(source)
    except TypeError as exc:
        raise IngestError("Chat must be a JSON array, export object, or message iterable") from exc


def chat_signal(source, duration: float, *, offset: float = 0) -> list[dict]:
    """Dense one-second bins with numeric signals suitable for Candidate.signals.

    Supports TwitchDownloader comments and chat-downloader messages. Invalid
    records and out-of-range timestamps are ignored; text/users are not retained.
    """
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(offset):
        raise IngestError("Chat duration must be positive and offsets finite")
    bins = [[0, 0, 0] for _ in range(math.ceil(duration))]
    for record in _messages(source):
        if not isinstance(record, dict):
            continue
        raw_time = record.get("content_offset_seconds", record.get("time_in_seconds", record.get("offset")))
        try:
            timestamp = float(raw_time) + offset
        except (TypeError, ValueError):
            continue
        if not math.isfinite(timestamp) or not 0 <= timestamp < duration:
            continue
        message = record.get("message", record.get("text", ""))
        if isinstance(message, dict):
            body = message.get("body")
            if body is None:
                body = "".join(f.get("text", "") for f in message.get("fragments", []) if isinstance(f, dict))
        else:
            body = message
        if not isinstance(body, str):
            continue
        bucket = bins[int(timestamp)]
        bucket[0] += 1
        bucket[1] += len(EMOTES.findall(body))
        bucket[2] += int(bool(CLIP_IT.search(body)))
    emote_counts = [b[1] for b in bins]
    mean = sum(emote_counts) / len(bins)
    std = math.sqrt(sum((value - mean)**2 for value in emote_counts) / len(bins))
    return [{"start": float(i), "end": min(i + 1.0, duration), "signals": {
        "chat_activity": activity,
        "chat_emotes": emotes,
        "chat_emote_spike": max(0.0, (emotes - mean) / std) if std else 0.0,
        "chat_clip_it": clips,
    }} for i, (activity, emotes, clips) in enumerate(bins)]


def twitch_messages(vod_id: str, duration: float, *, offset: float = 0):
    """Stream replay messages without persisting user chat or credentials."""
    if not re.fullmatch(r"[0-9]+", str(vod_id)):
        raise IngestError("twitch_vod_id must contain only digits")
    if not math.isfinite(offset):
        raise IngestError("chat_offset must be finite")
    try:
        from chat_downloader import ChatDownloader
    except ImportError as exc:
        raise IngestError("Twitch replay needs optional chat-downloader, or supply chat_log JSON") from exc
    downloader = ChatDownloader()
    try:
        yield from downloader.get_chat(
            f"https://www.twitch.tv/videos/{vod_id}", start_time=max(0, -offset),
            end_time=max(0, duration - offset), max_attempts=3,
        )
    finally:
        downloader.close()
