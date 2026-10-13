"""Conservative event-local targeting. Uncertain masks never become an effect."""
from dataclasses import dataclass
import warnings

import cv2
import numpy as np

from .backends import BoundedBackend, Config
from .tracking import MaskClip


@dataclass(frozen=True)
class TargetPrompt:
    point: tuple
    box: tuple


def profile_crosshair(profile=None):
    """Profiles may calibrate crosshair_center; existing FPS profiles use center."""
    if isinstance(profile, str):
        from profiles import get_profile
        profile = get_profile(profile)
    layout = getattr(profile, 'detection_layout', {}) if profile is not None else {}
    return tuple(layout.get('crosshair_center', (.5, .5)))


def target_prompt(shape, crosshair=(.5, .5)):
    h, w = shape
    cx, cy = crosshair
    if not np.isfinite(crosshair).all() or not (0 < cx < 1 and 0 < cy < 1):
        raise ValueError('crosshair must be normalized inside the frame')
    return TargetPrompt((cx*w, cy*h), (max(0, cx-.09)*w, max(0, cy-.14)*h,
                                       min(1, cx+.09)*w, min(1, cy+.18)*h))


def rejection(mask, crosshair=(.5, .5), previous=None, hud_boxes=()):
    """Return a stable diagnostic, or None. Geometry is normalized to this frame."""
    if mask.ndim != 2 or not np.isfinite(mask).all():
        return 'invalid mask'
    binary = (mask > 0).astype(np.uint8)
    h, w = binary.shape
    area = binary.mean()
    if area < .001:
        return 'too small'
    if area > .25:
        return 'too large'
    if binary[:2].any() or binary[-2:].any() or binary[:, :2].any() or binary[:, -2:].any():
        return 'frame edge'
    # Persistent HUD bands plus conservative FPS weapon exclusion.
    boxes = ((0, 0, 1, .10), (0, .88, 1, 1), (.38, .70, 1, 1), *hud_boxes)
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        if binary[int(y1*h):int(y2*h), int(x1*w):int(x2*w)].any():
            return 'viewmodel' if i == 2 else 'HUD'
    y, x = np.nonzero(binary)
    distance = ((x/w-crosshair[0])/.10)**2 + ((y/h-crosshair[1])/.12)**2
    if distance.min() > 1:
        return 'away from crosshair'
    # A target must be one compact component, not scattered scenery fragments.
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary)
    if n > 2 and stats[1:, cv2.CC_STAT_AREA].max()/binary.sum() < .95:
        return 'fragmented'
    if previous is not None:
        old = previous > 0
        iou = np.logical_and(binary, old).sum()/max(1, np.logical_or(binary, old).sum())
        if iou < .40:
            return 'unstable IoU'
    return None


def target_masks(video, start, end, kill_time, *, config=None, crosshair=(.5, .5), hud_boxes=()):
    """Sample every ~0.1 s around the kill; reject the whole effect on any failure."""
    config = config or Config.from_env()
    cap = cv2.VideoCapture(str(video))
    backend = BoundedBackend(config)
    reason = None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not cap.isOpened() or not np.isfinite([fps, start, end, kill_time]).all() or fps <= 0 or start < 0 or end <= start:
            raise ValueError('Invalid video or clip range')
        first, stop = int(np.ceil(start*fps-1e-6)), min(count, int(np.ceil(end*fps-1e-6)))
        if not first <= kill_time*fps < stop:
            raise ValueError('kill_time must lie inside the decoded clip')
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        low, high = max(first, round(kill_time*fps)-int(.3*fps)), min(stop-1, round(kill_time*fps)+int(.3*fps))
        indices = np.unique(np.linspace(low, high, min(config.max_samples, 7, high-low+1)).astype(int))
        # Even sample budgets must still include the actual kill frame.
        anchor = min(stop-1, max(first, round(kill_time*fps)))
        indices[np.argmin(np.abs(indices-anchor))] = anchor
        indices = np.sort(indices)
        masks = []
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = cap.read()
            if not ok:
                raise ValueError('Could not decode target frame')
            scale = min(1, 768/max(w, h))
            frame = cv2.resize(frame, (round(w*scale), round(h*scale)))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            seed = target_prompt(frame.shape[:2], crosshair)
            if config.backend == 'fallback':
                reason = 'model unavailable'
                break
            mask = backend.segment(frame, 'enemy at crosshair', seed)
            if isinstance(mask, TargetPrompt) or backend.failed:
                reason = 'model failed or exhausted budget'
                break
            reason = rejection(mask, crosshair, masks[-1] if masks else None, hud_boxes)
            if reason:
                break
            masks.append(mask)
        if not reason and len(masks) < 2:
            reason = 'insufficient temporal evidence'
        if reason:
            warnings.warn('SAM spotlight skipped: '+reason, RuntimeWarning, stacklevel=2)
            masks = [np.zeros((h, w), np.uint8)]
            indices = np.array([round(kill_time*fps)])
        return MaskClip(indices/fps, np.stack(masks), fps, first, stop, w, h, bool(reason))
    finally:
        backend.close()
        cap.release()
