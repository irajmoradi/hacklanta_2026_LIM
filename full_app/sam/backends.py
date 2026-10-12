"""Optional model adapters. Inputs are RGB uint8; outputs are binary HxW masks."""
import base64
import json
import multiprocessing as mp
import os
from dataclasses import dataclass, field
from urllib.request import Request, urlopen

import cv2
import numpy as np


@dataclass(frozen=True)
class Config:
    backend: str = "fallback"
    url: str = ""
    key: str = field(default="", repr=False)
    timeout: float = 2.0
    budget: float = 6.0
    max_samples: int = 12
    checkpoint: str = ""
    model_config: str = "configs/sam2.1/sam2.1_hiera_s.yaml"
    device: str = "cpu"

    def __post_init__(self):
        if self.backend not in {"fallback", "remote", "local"}:
            raise ValueError("Unknown SAM backend")
        if not (0 < self.timeout <= 120 and 0 < self.budget <= 300):
            raise ValueError("SAM timeout/budget must be positive and bounded")
        if not 1 <= self.max_samples <= 240:
            raise ValueError("max_samples must be in [1, 240]")

    @classmethod
    def from_env(cls):
        return cls(backend=os.getenv("SAM_BACKEND", "fallback"),
                   url=os.getenv("SAM_ENDPOINT_URL", ""), key=os.getenv("SAM_API_KEY", ""),
                   timeout=float(os.getenv("SAM_TIMEOUT", "2")),
                   budget=float(os.getenv("SAM_CLIP_BUDGET", "6")),
                   max_samples=int(os.getenv("SAM_MAX_SAMPLES", "12")),
                   checkpoint=os.getenv("SAM2_CHECKPOINT", ""),
                   model_config=os.getenv("SAM2_CONFIG", cls.model_config),
                   device=os.getenv("SAM2_DEVICE", "cpu"))


def fallback_mask(frame, previous=None):
    """Motion + border-color contrast, retaining one coherent salient component."""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    border = np.concatenate([frame[0], frame[-1], frame[:, 0], frame[:, -1]])
    contrast = np.max(np.abs(frame.astype(float) - np.median(border, axis=0)), axis=2)
    score = contrast
    if previous is not None:
        motion = cv2.absdiff(gray, cv2.cvtColor(previous, cv2.COLOR_RGB2GRAY))
        score = np.maximum(score, motion)
    binary = (score > max(18, float(np.percentile(score, 65)))).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(binary)
    h, w = gray.shape
    choices = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= h*w*.002]
    if choices:
        best = max(choices, key=lambda i: stats[i, cv2.CC_STAT_AREA] /
                   (1 + 3 * np.linalg.norm((centers[i] - [w/2, h/2]) / [w, h])))
        return (labels == best).astype(np.uint8)
    # Stable center prior for static/blank scenes, rather than an empty crop.
    result = np.zeros((h, w), np.uint8)
    cv2.ellipse(result, (w//2, h//2), (max(1, w//6), max(1, h//3)), 0, 0, 360, 1, -1)
    return result


def validate_mask(mask, shape):
    mask = np.asarray(mask)
    if mask.shape != shape or not np.isfinite(mask).all():
        raise ValueError("Invalid mask shape or values")
    if not np.isin(mask, [0, 1, 255]).all() or not np.any(mask):
        raise ValueError("Expected a nonempty binary mask")
    return (mask > 0).astype(np.uint8)


class RemoteSegmenter:
    def __init__(self, config):
        self.config = config

    def segment(self, frame, prompt, seed):
        ok, encoded = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        if not ok:
            raise ValueError("Could not encode frame")
        payload = json.dumps({"image_png": base64.b64encode(encoded).decode(),
                              "prompt": prompt}).encode()
        headers = {"Content-Type": "application/json"}
        if self.config.key:
            headers["Authorization"] = "Bearer " + self.config.key
        request = Request(self.config.url, data=payload, headers=headers, method="POST")
        with urlopen(request, timeout=self.config.timeout) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Oversized mask response")
        return validate_mask(json.loads(body)["mask"], frame.shape[:2])


class LocalSegmenter:
    def __init__(self, config):
        # No implicit downloads; imports and model loading happen only in worker.
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        self.predictor = SAM2ImagePredictor(build_sam2(
            config.model_config, config.checkpoint, device=config.device))

    def segment(self, frame, prompt, seed):
        import torch
        y, x = np.nonzero(seed)
        box = np.array([x.min(), y.min(), x.max(), y.max()])
        with torch.inference_mode():
            self.predictor.set_image(frame)
            masks, scores, _ = self.predictor.predict(box=box, multimask_output=True)
        return validate_mask(masks[np.argmax(scores)], frame.shape[:2])


def _worker(connection, config):
    try:
        backend = RemoteSegmenter(config) if config.backend == "remote" else LocalSegmenter(config)
        connection.send("ready")
        while True:
            frame, prompt, seed = connection.recv()
            connection.send(backend.segment(frame, prompt, seed))
    except Exception:
        # Do not send exception strings: provider errors can contain credentials.
        try:
            connection.send(None)
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class BoundedBackend:
    """Killable persistent worker, with a per-clip circuit breaker and total budget."""
    def __init__(self, config):
        self.config = config
        self.remaining = config.budget
        self.process = None
        self.connection = None
        self.failed = False

    def segment(self, frame, prompt, seed):
        import time
        if self.failed or self.remaining <= 0 or self.config.backend == "fallback":
            return seed
        started = time.monotonic()
        try:
            if self.process is None:
                context = mp.get_context("spawn")
                self.connection, child = context.Pipe()
                self.process = context.Process(target=_worker, args=(child, self.config), daemon=True)
                self.process.start()
                child.close()
                wait = min(self.config.timeout, self.remaining) - (time.monotonic() - started)
                if wait <= 0 or not self.connection.poll(wait) or self.connection.recv() != "ready":
                    raise TimeoutError()
            self.connection.send((frame, prompt, seed))
            wait = min(self.config.timeout, self.remaining) - (time.monotonic() - started)
            if wait <= 0 or not self.connection.poll(wait):
                raise TimeoutError()
            return validate_mask(self.connection.recv(), frame.shape[:2])
        except Exception:
            self.failed = True
            self.close()
            return seed
        finally:
            self.remaining -= time.monotonic() - started

    def close(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=.2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=.2)
            self.process.close()
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
