"""Probe actual encoder operation, not merely FFmpeg's compiled encoder list."""
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Encoder:
    name: str = "libx264"
    threads: int = 2
    device: str = "/dev/dri/renderD128"

    @property
    def hardware(self):
        return self.name != "libx264"

    def input_args(self):
        return ["-vaapi_device", self.device] if self.name == "h264_vaapi" else []

    def upload_filter(self):
        return ",format=nv12,hwupload" if self.name == "h264_vaapi" else ""

    def args(self, preset="preview"):
        if preset not in ("preview", "draft", "final"):
            raise ValueError("preset must be preview, draft or final")
        opts = {
            "libx264": ["-preset", {"preview": "veryfast", "draft": "superfast", "final": "faster"}[preset], "-crf", "22"],
            "h264_nvenc": ["-preset", "p4", "-cq", "22"],
            "h264_qsv": ["-preset", "veryfast", "-global_quality", "22"],
            "h264_vaapi": ["-qp", "22"],
            "h264_videotoolbox": ["-b:v", "8M"],
        }[self.name]
        if self.name == "libx264" and preset != "final":
            opts += ["-tune", "fastdecode"]
        return ["-c:v", self.name, *opts, "-threads", str(self.threads)]


@lru_cache(maxsize=16)
def best(prefer_hardware=True, threads=None):
    threads = threads or min(4, max(1, os.cpu_count() or 1))
    if prefer_hardware:
        for name in ("h264_nvenc", "h264_qsv", "h264_vaapi", "h264_videotoolbox"):
            enc = Encoder(name, threads)
            cmd = ["ffmpeg", "-v", "error", *enc.input_args(), "-f", "lavfi", "-i",
                   "color=s=128x128:d=0.1", "-vf", "format=yuv420p" + enc.upload_filter(),
                   *enc.args(), "-f", "null", "-"]
            try:
                if subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0:
                    return enc
            except (OSError, subprocess.TimeoutExpired):
                pass
    return Encoder(threads=threads)
