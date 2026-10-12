"""Bounded-memory media operations and a process-safe, atomic disk cache."""

from contextlib import contextmanager
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

from .models import IngestError, Limits
from server.security import validate_media_metadata


def run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True,
                                timeout=30 if args[0] == 'ffprobe' else 3600)
    except FileNotFoundError as exc:
        raise IngestError(f"Required executable is missing: {args[0]}") from exc
    except subprocess.TimeoutExpired:
        raise IngestError('Media processing timed out') from None
    except subprocess.CalledProcessError:
        raise IngestError('Media processing failed; input may be invalid') from None
    return result.stdout


def probe(path: Path) -> dict:
    path = Path(path).resolve()
    sniff_video(path)
    try:
        data = json.loads(run([
            "ffprobe", "-v", "error", "-max_alloc", "67108864",
            "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm,avi,flv,mpegts,mpeg",
            "-probesize", "5000000", "-analyzeduration", "5000000",
            "-show_entries", "format=duration:stream=codec_type,duration,avg_frame_rate,index,width,height:stream_disposition=attached_pic",
            "-of", "json", str(path),
        ]))
    except IngestError:
        raise
    except (ValueError, TypeError):
        raise IngestError('Invalid video probe response') from None
    video = next((s for s in data.get("streams", [])
                  if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise IngestError("Input has no video stream")
    try:
        duration = float(video.get("duration") or data["format"]["duration"])
        fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
        container_duration = float(data.get("format", {}).get("duration") or duration)
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise IngestError("Input has no usable duration/frame rate") from exc
    if (not math.isfinite(duration) or duration <= 0 or fps <= 0
            or not math.isfinite(container_duration) or container_duration <= 0):
        raise IngestError("Input has no usable duration/frame rate")
    info = {"duration": duration, "container_duration": container_duration,
            "fps": fps, "video_index": video["index"],
            "width": video["width"], "height": video["height"]}
    try:
        return validate_media_metadata(info)
    except ValueError as exc:
        raise IngestError(str(exc)) from None


def sniff_video(path):
    """Reject playlists, archives, images and extension-only spoofing before probing."""
    with Path(path).open('rb') as stream:
        header = stream.read(512)
    if header.startswith(b'RIFF') and header[8:12] == b'WAVE':
        raise IngestError('Input has no video stream')
    supported = (header[4:8] in (b'ftyp', b'moov', b'mdat', b'wide')
                 or header.startswith(b'\x1aE\xdf\xa3')
                 or header.startswith(b'RIFF') and header[8:12] == b'AVI '
                 or header.startswith(b'FLV')
                 or len(header) > 376 and header[0] == header[188] == header[376] == 0x47
                 or header.startswith(b'\x00\x00\x01\xba'))
    if not supported:
        raise IngestError('Unsupported video container signature')


def check_file(path: Path, limits: Limits) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise IngestError("Input must be a nonempty local video file")
    if path.stat().st_size > limits.max_bytes:
        raise IngestError("Input exceeds max_bytes")


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def encode(source: Path, target: Path, *, height: int | None = None,
           start: float | None = None, duration: float | None = None) -> None:
    info = probe(source)
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if start is not None:
        args += ["-ss", f"{start:.9f}"]
    args += ["-max_alloc", "67108864", "-protocol_whitelist", "file",
             "-format_whitelist", "mov,matroska,webm,avi,flv,mpegts,mpeg",
             "-i", str(Path(source).resolve())]
    if duration is not None:
        args += ["-t", f"{duration:.9f}"]
    scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if height:
        scale = f"scale=-2:trunc(min(ih\\,{height})/2)*2"
    args += [
        "-map", f"0:{info['video_index']}", "-map", "0:a:0?",
        "-vf", f"fps=30,{scale}", "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23" if height is None else "28",
        "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
        "-threads", "2", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
        "-af", "aresample=48000:async=1", "-map_metadata", "-1", "-movflags", "+faststart",
        str(target),
    ]
    run(args)


@contextmanager
def cache_lock(path: Path, timeout: float = 3600):
    """OS locks release on process exit; never delete the shared lock file."""
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise IngestError("Timed out waiting for the ingest cache lock")
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def cached(directory: Path, expected_files: set[str], *, has_duration: bool = False) -> dict | None:
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        if (not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict)
                or set(manifest["files"]) != expected_files):
            return None
        if has_duration:
            duration = manifest["duration"]
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                return None
        for name, size in manifest["files"].items():
            if Path(name).name != name or size <= 0 or (directory / name).stat().st_size != size:
                return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_manifest(directory: Path, **metadata) -> None:
    metadata["files"] = {p.name: p.stat().st_size for p in directory.glob("*.mp4")}
    (directory / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
