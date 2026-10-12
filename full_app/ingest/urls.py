"""Optional yt-dlp adapter. Only import videos the caller owns or may use."""

import math
from pathlib import Path
import time
import tempfile

from server.security import https_url, safe_path

from .models import IngestError, Limits, Progress


def download(url: str, directory: Path, *, limits: Limits, owns_content: bool,
             progress: Progress | None = None) -> Path:
    """Publish only a complete video; clean partials even for direct callers."""
    directory = Path(directory).resolve()
    with tempfile.TemporaryDirectory(prefix='url-', dir=directory) as temporary:
        result = _download(url, Path(temporary), limits=limits,
                           owns_content=owns_content, progress=progress)
        target = safe_path(directory, result.name)
        if target.exists():
            raise IngestError('Download destination already exists')
        result.replace(target)
        return target


def _download(url: str, directory: Path, *, limits: Limits, owns_content: bool,
              progress: Progress | None = None) -> Path:
    if not owns_content:
        raise IngestError("URL import requires owns_content=True (ownership or permission)")
    hosts = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
             "twitch.tv", "www.twitch.tv", "clips.twitch.tv"}
    try:
        https_url(url, hosts)
    except ValueError:
        raise IngestError("Only HTTPS Twitch/YouTube video URLs are supported") from None
    try:
        import yt_dlp
    except ImportError as exc:
        raise IngestError("URL import needs optional yt-dlp: pip install yt-dlp") from exc

    def check_info(info, *, incomplete=False):
        # Progressive HTTPS only: manifest downloaders can fall back to external
        # ffmpeg networking, bypassing our socket policy. Fail closed instead.
        for item in [info, *(info.get('requested_formats') or [])]:
            if item.get('protocol') not in (None, 'https'):
                raise IngestError('URL import requires a progressive HTTPS video')
            if item.get('url'):
                from .network import validate_target
                validate_target(item['url'])
        if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
            raise IngestError("Import a single VOD or clip, not a playlist")
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
            raise IngestError("Live/upcoming streams are not finite VODs")
        duration = info.get("duration")
        if duration is None and incomplete:
            return
        try:
            duration = float(duration)
        except (ValueError, TypeError) as exc:
            raise IngestError("URL must have a known finite duration") from exc
        if not math.isfinite(duration) or duration <= 0 or duration > limits.max_duration:
            raise IngestError("URL duration is invalid or exceeds max_duration")
        formats = info.get("requested_formats") or [info]
        size = sum(f.get("filesize") or f.get("filesize_approx") or 0 for f in formats)
        if size > limits.max_bytes:
            raise IngestError("URL exceeds max_bytes")

    def match_filter(info, *, incomplete=False):
        check_info(info, incomplete=incomplete)
        return None

    downloaded = {}

    def hook(event):
        # Count completed and active streams together (separate video/audio).
        key = event.get("filename") or event.get("tmpfilename") or "media"
        downloaded[key] = max(downloaded.get(key, 0), event.get("downloaded_bytes") or 0)
        total = sum(downloaded.values())
        if total > limits.max_bytes:
            raise IngestError("Download exceeds max_bytes")
        if progress:
            progress({"stage": "download", "status": event.get("status"),
                      "downloaded_bytes": total,
                      "total_bytes": event.get("total_bytes") or event.get("total_bytes_estimate")})

    options = {
        "outtmpl": str(directory / "source.%(ext)s"),
        "format": "b[protocol=https]", "merge_output_format": "mp4",
        "noplaylist": True, "playlistend": 1, "quiet": True, "no_warnings": True,
        "max_filesize": limits.max_bytes, "match_filter": match_filter,
        "progress_hooks": [hook], "socket_timeout": 30, "retries": 2,
        "fragment_retries": 2, "concurrent_fragment_downloads": 1,
        "proxy": "", "enable_file_urls": False,
        "logger": _QuietLogger(),
    }
    deadline = time.monotonic() + 1800

    class SafeYoutubeDL(yt_dlp.YoutubeDL):
        def urlopen(self, request):
            from .network import open_request
            return open_request(request, limit=limits.max_bytes, deadline=deadline)

    if progress:
        progress({"stage": "download", "status": "metadata"})
    try:
        with SafeYoutubeDL(options) as client:
            info = client.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise IngestError("URL did not resolve to a video")
            check_info(info)
            client.process_ie_result(info, download=True)
    except IngestError:
        raise
    except Exception:
        raise IngestError("URL download failed; check access, availability, and yt-dlp installation") from None
    candidates = [p for p in directory.glob("source.*")
                  if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".flv", ".ts")]
    if len(candidates) != 1:
        raise IngestError("Download did not produce one complete video")
    from .media import check_file
    safe_path(directory, candidates[0].name)
    check_file(candidates[0], limits)
    return candidates[0]


class _QuietLogger:
    """yt-dlp diagnostics may contain signed URLs or credentials."""
    def debug(self, message):
        pass

    warning = error = debug
