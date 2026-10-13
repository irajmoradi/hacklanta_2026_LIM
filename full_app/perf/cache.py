"""Disk cache with atomic publication; failed builds never become cache hits."""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from .media import run


class Cache:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._keys = {}

    def get(self, kind, sources, options, suffix, build):
        stamps = [(str(Path(p).resolve()), Path(p).stat().st_size, Path(p).stat().st_mtime_ns) for p in sources]
        key = hashlib.sha256(json.dumps([1, kind, stamps, options], sort_keys=True).encode()).hexdigest()
        target = self.root / (key + suffix)
        with self._lock:
            key_lock = self._keys.setdefault(key, threading.RLock())
        # Different assets can build concurrently; identical requests coalesce.
        with key_lock:
            if target.exists() and target.stat().st_size:
                return target
            fd, name = tempfile.mkstemp(dir=self.root, suffix=suffix)
            os.close(fd)
            temp = Path(name)
            try:
                build(temp)
                if not temp.stat().st_size:
                    raise RuntimeError("empty cache artifact")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        return target

    def audio(self, source, rate=48000, channels=2):
        return self.get("audio", [source], [rate, channels], ".wav", lambda out: run([
            "ffmpeg", "-v", "error", "-y", "-i", source, "-vn", "-ar", rate, "-ac", channels, "-c:a", "pcm_s16le", out]))

    def proxy(self, source, height=360, fps=30):
        return self.get("proxy", [source], [height, fps], ".mp4", lambda out: run([
            "ffmpeg", "-v", "error", "-y", "-i", source, "-vf", f"scale=-2:{height},fps={fps}",
            "-c:v", "libx264", "-preset", "superfast", "-crf", "28", "-threads", "2",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", out]))

    def overlay(self, sources, options, build):
        """Cache a caller-rendered PNG; include font/style/size in options."""
        return self.get("overlay", sources, options, ".png", build)
