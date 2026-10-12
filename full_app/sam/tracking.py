"""Clip-scoped mask cache and normalized, smoothed per-frame subject tracks."""
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import threading

import cv2
import numpy as np

from .backends import BoundedBackend, Config, fallback_mask


@dataclass(frozen=True)
class MaskClip:
    times: np.ndarray
    masks: np.ndarray
    fps: float
    first: int
    stop: int
    width: int
    height: int
    degraded: bool

    def mask_at(self, time: float) -> np.ndarray:
        index = int(np.argmin(np.abs(self.times - time)))
        return cv2.resize(self.masks[index], (self.width, self.height), interpolation=cv2.INTER_NEAREST)


_cache = OrderedDict()
_lock = threading.Lock()
_CACHE_BYTES = 32 * 1024 * 1024


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def clip_masks(video: str | Path, start: float, end: float, *, prompt: str = "player character",
               config: Config | None = None) -> MaskClip:
    config = config or Config.from_env()
    if not np.isfinite([start, end]).all() or start < 0 or end <= start:
        raise ValueError("Expected 0 <= start < end")
    path = Path(video).resolve(strict=True)
    stat = path.stat()
    # Config is never serialized; credentials remain in process memory only.
    key = (str(path), stat.st_size, stat.st_mtime_ns, start, end, prompt, config)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    cap = cv2.VideoCapture(str(path))
    backend = BoundedBackend(config)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not cap.isOpened() or not np.isfinite(fps) or fps <= 0 or count <= 0:
            raise ValueError("Could not decode video metadata")
        first = int(np.ceil(start * fps - 1e-6))
        stop = min(count, int(np.ceil(end * fps - 1e-6)))
        if first >= stop:
            raise ValueError("Clip is outside the video")
        samples = min(config.max_samples, stop-first, max(2, int((end-start)*4)+1))
        indices = np.unique(np.linspace(first, stop-1, samples).astype(int))
        masks = []
        previous = None
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = cap.read()
            if not ok:
                raise ValueError("Could not decode clip frame")
            h, w = frame.shape[:2]
            scale = min(1, 256 / max(h, w))
            small = cv2.resize(frame, (max(1, round(w*scale)), max(1, round(h*scale))))
            small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            seed = fallback_mask(small, previous)
            masks.append(backend.segment(small, prompt, seed))
            previous = small
        result = MaskClip(indices/fps, np.stack(masks), fps, first, stop, w, h,
                          backend.failed or (config.backend != "fallback" and backend.remaining <= 0))
        result.times.flags.writeable = False
        result.masks.flags.writeable = False
    finally:
        cap.release()
        backend.close()
    with _lock:
        _cache[key] = result
        while sum(v.masks.nbytes for v in _cache.values()) > _CACHE_BYTES or len(_cache) > 16:
            _cache.popitem(last=False)
    return result


def track_from_masks(clip: MaskClip) -> list[tuple[float, float, float, float, float]]:
    boxes = []
    for mask in clip.masks:
        y, x = np.nonzero(mask)
        h, w = mask.shape
        boxes.append([(x.min()+x.max()+1)/(2*w), (y.min()+y.max()+1)/(2*h),
                      (x.max()-x.min()+1)/w, (y.max()-y.min()+1)/h])
    times = np.arange(clip.first, clip.stop)/clip.fps
    boxes = np.asarray(boxes)
    interpolated = np.column_stack([np.interp(times, clip.times, boxes[:, j]) for j in range(4)])
    # Limit pan/size velocity to 0.6 normalized units/second, independent of FPS.
    smooth = interpolated.copy()
    alpha = 1-np.exp(-1/(clip.fps*.15))
    for i in range(1, len(smooth)):
        smooth[i] = smooth[i-1] + np.clip(alpha*(interpolated[i]-smooth[i-1]), -.6/clip.fps, .6/clip.fps)
    return [tuple(map(float, row)) for row in np.column_stack([times, smooth])]


def subject_track(video: str | Path, start: float, end: float, **kwargs) -> list[tuple[float, float, float, float, float]]:
    """Return (absolute seconds, cx, cy, width, height), all geometry normalized."""
    clip = clip_masks(video, start, end, **kwargs)
    if clip.degraded:
        import warnings
        warnings.warn('SAM subject tracking degraded; using motion/contrast fallback', RuntimeWarning)
    return track_from_masks(clip)
