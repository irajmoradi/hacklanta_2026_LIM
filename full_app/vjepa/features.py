"""Bounded-memory ffmpeg window decoding, frozen encoders, content-addressed cache."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from zipfile import BadZipFile

import numpy as np

from .media import probe_media


@dataclass(frozen=True)
class WindowConfig:
    frames: int = 32
    fps: float = 8.0
    resolution: int = 256
    stride: float = 2.0

    def __post_init__(self):
        if not 16 <= self.frames <= 64 or self.frames % 2:
            raise ValueError("frames must be even and between 16 and 64")
        if (not math.isfinite(self.fps) or self.fps <= 0 or
                not math.isfinite(self.stride) or not 0 < self.stride <= self.frames / self.fps or
                self.resolution < 16 or self.resolution % 16):
            raise ValueError("positive fps, stride <= window length, resolution multiple of 16 required")


def windows(duration: float, config: WindowConfig) -> list[tuple[float, float]]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be finite and positive")
    length = config.frames / config.fps
    result = []
    start = 0.0
    while start < duration:
        result.append((start, min(start + length, duration)))
        if start + length >= duration:
            break
        start = len(result) * config.stride
    return result


def video_duration(path: str | Path) -> float:
    data = probe_media(path, select_streams="v:0", entries="stream=duration:format=duration")
    if not data.get("streams"):
        raise ValueError("input has no video stream")
    return float(data["streams"][0].get("duration", data["format"]["duration"]))


def decode(path: str | Path, start: float, end: float, config: WindowConfig) -> np.ndarray:
    filters = f"fps={config.fps},scale={config.resolution}:{config.resolution}"
    result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path),
                             "-t", str(end - start), "-vf", filters, "-frames:v", str(config.frames),
                             "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                            check=True, capture_output=True)
    frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, config.resolution, config.resolution, 3)
    if not len(frames):
        raise ValueError(f"no decoded frames at {start}")
    if len(frames) < config.frames:
        frames = np.concatenate([frames, np.repeat(frames[-1:], config.frames - len(frames), axis=0)])
    return frames


class TinyEncoder:
    """Seeded random projection of RGB statistics; strictly a test stand-in."""
    def __init__(self, seed=13, dimension=12):
        self.identity = f"tiny-v1:{seed}:{dimension}"
        self.weights = np.random.default_rng(seed).normal(size=(6, dimension)).astype(np.float32)

    def encode(self, videos):
        x = np.asarray(videos, dtype=np.float32) / 255
        stats = np.concatenate([x.mean(axis=(1, 2, 3)), x.std(axis=(1, 2, 3))], axis=1)
        return np.tanh(stats @ self.weights)


class HFEncoder:
    def __init__(self, model_id="facebook/vjepa2-vitl-fpc64-256", revision="main", device="cpu"):
        import torch
        from transformers import AutoModel, AutoVideoProcessor
        if not model_id.startswith("facebook/vjepa2-"):
            raise ValueError("expected a facebook/vjepa2-* checkpoint")
        self.processor = AutoVideoProcessor.from_pretrained(model_id, revision=revision)
        self.model = AutoModel.from_pretrained(model_id, revision=revision).to(device).eval()
        resolved = getattr(self.model.config, "_commit_hash", None) or revision
        self.identity = f"hf-mean-v1:{model_id}@{resolved}"
        self.device, self.torch = device, torch

    def encode(self, videos):
        # Decoding already sampled/resized; preserve the requested temporal/spatial grid.
        inputs = self.processor(videos=list(videos), return_tensors="pt", do_resize=False,
                                do_center_crop=False, do_sample_frames=False).to(self.device)
        with self.torch.inference_mode():
            features = self.model.get_vision_features(**inputs)
        return features.mean(dim=1).float().cpu().numpy()


def atomic_npz(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as handle:
        temporary = handle.name
    try:
        np.savez_compressed(temporary, **arrays)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def extract(video_path, encoder, cache_dir, config=None, batch_size=4):
    config = config or WindowConfig()
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    digest = hashlib.sha256()
    with open(video_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    duration = video_duration(video_path)
    bounds = windows(duration, config)
    features, pending = [None] * len(bounds), []
    cache_dir = Path(cache_dir)

    def flush():
        if not pending:
            return
        vectors = np.asarray(encoder.encode([decode(video_path, *bounds[i], config) for i, _ in pending]))
        if vectors.ndim != 2 or len(vectors) != len(pending) or not np.isfinite(vectors).all():
            raise ValueError("encoder must return finite [batch, dimension] features")
        for (i, path), vector in zip(pending, vectors):
            features[i] = vector
            atomic_npz(path, feature=vector)
        pending.clear()

    for i, bound in enumerate(bounds):
        key = json.dumps([digest.hexdigest(), bound, asdict(config), encoder.identity], sort_keys=True)
        path = cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".npz")
        if path.exists():
            try:
                with np.load(path, allow_pickle=False) as data:
                    vector = data["feature"]
                    if vector.ndim != 1 or not np.isfinite(vector).all():
                        raise ValueError("invalid cache")
                    features[i] = vector
                continue
            except (ValueError, OSError, KeyError, EOFError, BadZipFile):
                pass  # Interrupted/corrupt cache entries are recomputed.
        pending.append((i, path))
        if len(pending) == batch_size:
            flush()
    flush()
    return {"features": np.stack(features), "windows": np.asarray(bounds), "duration": duration,
            "encoder": encoder.identity, "config": asdict(config)}
