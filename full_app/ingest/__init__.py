"""Prepare local or owned remote gameplay for analysis, with reusable proxies."""

import math
from pathlib import Path
import shutil
import tempfile

from . import media
from .models import Chunk, IngestError, Limits, PreparedVideo, Progress

__all__ = ["prepare", "Chunk", "PreparedVideo", "Limits", "IngestError"]


def chunk_ranges(duration: float, chunk_seconds: float, overlap_seconds: float):
    """Frame-aligned ranges cover the timeline without an extra overlap-only tail."""
    if not all(math.isfinite(x) for x in (duration, chunk_seconds, overlap_seconds)):
        raise IngestError("Chunk parameters must be finite")
    length, overlap = round(chunk_seconds * 30), round(overlap_seconds * 30)
    if duration <= 0 or length < 1 or overlap_seconds < 0 or not 0 <= overlap < length:
        raise IngestError("Require duration > 0 and 0 <= overlap < chunk_seconds")
    total, start = max(1, round(duration * 30)), 0
    while start < total:
        end = min(start + length, total)
        yield start / 30, end / 30
        if end == total:
            break
        start += length - overlap


def prepare(source: str | Path, *, cache_dir: str | Path | None = None,
            proxy_height: int = 480, chunk_seconds: float = 900,
            overlap_seconds: float = 15, limits: Limits | None = None,
            progress: Progress | None = None, owns_content: bool = False,
            chat_log=None, twitch_vod_id: str | None = None,
            chat_offset: float = 0) -> PreparedVideo:
    """Normalize once, cache by SHA-256, and return independent analysis chunks.

    URL imports require owns_content=True. Chat timestamps must be relative to
    the supplied video; chat_offset is added to replay offsets for trimmed VODs.
    See docs/ingest.md for optional download dependencies and signal semantics.
    """
    limits = limits or Limits()
    if proxy_height not in (480, 720):
        raise IngestError("proxy_height must be 480 or 720")
    list(chunk_ranges(1, chunk_seconds, overlap_seconds))  # Validate before any work.
    root = Path(cache_dir or Path(__file__).resolve().parents[1] / "workspace" / "ingest").resolve()
    root.mkdir(parents=True, exist_ok=True)

    def emit(stage, **details):
        if progress:
            progress({"stage": stage, **details})

    def local(path):
        return _prepare_local(Path(path).resolve(), root, proxy_height, chunk_seconds,
                              overlap_seconds, limits, emit)

    if str(source).lower().startswith(("http://", "https://")):
        from .urls import download
        # Private staging avoids retaining duplicate original downloads in cache.
        with tempfile.TemporaryDirectory(prefix="download-", dir=root) as staging:
            result = local(download(str(source), Path(staging), limits=limits,
                                    owns_content=owns_content, progress=progress))
    else:
        result = local(source)
    signal = None
    if chat_log is not None or twitch_vod_id is not None:
        from .chat import chat_signal, twitch_messages
        emit("chat")
        if chat_log is not None:
            signal = chat_signal(chat_log, result.duration, offset=chat_offset)
        else:
            messages = twitch_messages(twitch_vod_id, result.duration, offset=chat_offset)
            try:
                signal = chat_signal(messages, result.duration, offset=chat_offset)
            finally:
                messages.close()
    emit("complete", duration=result.duration)
    return PreparedVideo(result.path, result.proxy, result.duration, result.fps, result.chunks, signal)


def _prepare_local(source, root, height, chunk_seconds, overlap_seconds, limits, emit):
    media.check_file(source, limits)
    emit("probe")
    info = media.probe(source)
    if max(info["duration"], info["container_duration"]) > limits.max_duration:
        raise IngestError("Input exceeds max_duration")
    emit("hash")
    before = source.stat()
    digest = media.content_hash(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise IngestError("Input changed while hashing; retry after upload completes")
    base = root / f"{digest}-v1"
    with media.cache_lock(root / f"{digest}.lock"):
        base.mkdir(exist_ok=True)
        normalized = base / "normalized"
        normal_meta = media.cached(normalized, {"video.mp4"}, has_duration=True)
        if normal_meta is None:
            emit("normalize", cache_hit=False)
            with tempfile.TemporaryDirectory(prefix="normalize-", dir=base) as stage:
                staging = Path(stage)
                media.encode(source, staging / "video.mp4")
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise IngestError("Input changed during preparation; retry after upload completes")
                normal_info = media.probe(staging / "video.mp4")
                media.write_manifest(staging, duration=normal_info["duration"])
                _publish(staging, normalized)
            normal_meta = media.cached(normalized, {"video.mp4"}, has_duration=True)
        else:
            emit("normalize", cache_hit=True)
        duration = normal_meta["duration"]
        proxy_dir = base / f"proxy-{height}"
        if media.cached(proxy_dir, {"proxy.mp4"}) is None:
            emit("proxy", cache_hit=False)
            with tempfile.TemporaryDirectory(prefix="proxy-", dir=base) as stage:
                staging = Path(stage)
                media.encode(normalized / "video.mp4", staging / "proxy.mp4", height=height)
                media.write_manifest(staging)
                _publish(staging, proxy_dir)
        else:
            emit("proxy", cache_hit=True)
        proxy = proxy_dir / "proxy.mp4"
        ranges = list(chunk_ranges(duration, chunk_seconds, overlap_seconds))
        if len(ranges) == 1:
            chunks = [Chunk(proxy, *ranges[0])]
        else:
            length, overlap = round(chunk_seconds * 30), round(overlap_seconds * 30)
            chunk_dir = base / f"chunks-{height}-{length}-{overlap}"
            if media.cached(chunk_dir, {f"{i:05d}.mp4" for i in range(len(ranges))}) is None:
                with tempfile.TemporaryDirectory(prefix="chunks-", dir=base) as stage:
                    staging = Path(stage)
                    for index, (start, end) in enumerate(ranges):
                        emit("chunk", index=index, total=len(ranges), cache_hit=False)
                        media.encode(proxy, staging / f"{index:05d}.mp4", height=height,
                                     start=start, duration=end - start)
                    media.write_manifest(staging)
                    _publish(staging, chunk_dir)
            else:
                emit("chunk", cache_hit=True, total=len(ranges))
            chunks = [Chunk(chunk_dir / f"{i:05d}.mp4", start, end)
                      for i, (start, end) in enumerate(ranges)]
        return PreparedVideo(normalized / "video.mp4", proxy, duration, 30.0, chunks)


def _publish(staging: Path, target: Path):
    # Called under the per-content lock; interrupted jobs never publish a manifest.
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
