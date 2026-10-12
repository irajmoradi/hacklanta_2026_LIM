"""Sampled OCR with spatial union and temporal hold; text never enters tracks."""
import math
import unicodedata

import cv2

from .models import BlurBox, BlurTrack, PrivacyOptions
from .ocr import get_reader
from .profiles import regions_for


def normalized_name(text):
    return unicodedata.normalize("NFKC", text).strip().casefold()


def overlap(a, b):
    return (a.x < b.x + b.width and b.x < a.x + a.width and
            a.y < b.y + b.height and b.y < a.y + a.height)


def smooth(boxes):
    """Merge touching time windows with overlapping boxes of the same kind."""
    output = []
    for current in sorted(boxes, key=lambda b: b.start):
        for i in range(len(output) - 1, -1, -1):
            old = output[i]
            if old.kind == current.kind and old.end >= current.start and overlap(old, current):
                x, y = min(old.x, current.x), min(old.y, current.y)
                current = BlurBox(x=x, y=y, width=max(old.x + old.width, current.x + current.width)-x,
                                  height=max(old.y + old.height, current.y + current.height)-y,
                                  start=min(old.start, current.start), end=max(old.end, current.end), kind=old.kind)
                output.pop(i)
        output.append(current)
    return output


def detect_video(source, options=None, *, reader=None):
    """Accept a PrivacyOptions or JSON-like API dict; return a serializable track.

    An injected reader implements read(BGR_frame) -> list[Word]. Missing/failed
    OCR conservatively covers all configured regions, with explicit warnings.
    """
    options = PrivacyOptions.model_validate(options or {})
    regions = regions_for(options)
    capture = cv2.VideoCapture(str(source))
    try:
        width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps, count = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not capture.isOpened() or not all(math.isfinite(v) and v > 0 for v in (width, height, fps, count)):
            raise ValueError("cannot read source video metadata")
        duration = count / fps
        boxes, warnings = [], []
        for b in options.manual_boxes:
            if b.end > duration:
                raise ValueError("manual blur box exceeds source duration")
            boxes.append(b)
        if options.blur_webcam:
            if "webcam" not in regions:
                raise ValueError("blur_webcam requires a webcam profile region")
            boxes.append(BlurBox(**regions["webcam"].model_dump(), end=duration, kind="webcam"))
        active = {k: v for k, v in regions.items() if k != "webcam"}
        try:
            reader = reader if reader is not None else get_reader(options.backend)
        except Exception as exc:
            warnings.append(f"OCR unavailable ({type(exc).__name__}); using whole-region fallback")
            reader = None
        if reader is None:
            if active:
                warnings.append("Whole-region fallback cannot preserve the uploader name")
            boxes.extend(BlurBox(**b.model_dump(), end=duration, kind=k) for k, b in active.items())
        else:
            interval = 1 / options.sample_fps
            # Sample actual decoded frames sequentially: avoids inaccurate keyframe seeks.
            index, next_time = 0, 0.0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                t = index / fps
                index += 1
                if t + 1e-6 < next_time:
                    continue
                next_time = t + interval
                try:
                    words = reader.read(frame)
                except Exception as exc:
                    warnings.append(f"OCR failed ({type(exc).__name__}); using whole-region fallback")
                    boxes.extend(BlurBox(**b.model_dump(), end=duration, kind=k) for k, b in active.items())
                    break
                for word in words:
                    if options.keep_own_name and options.own_name and normalized_name(word.text) == normalized_name(options.own_name):
                        continue
                    cx, cy = (word.x + word.width / 2) / width, (word.y + word.height / 2) / height
                    kinds = [k for k, b in active.items() if b.x <= cx <= b.x+b.width and b.y <= cy <= b.y+b.height]
                    if not kinds:
                        continue
                    pad = options.padding_pixels
                    x, y = max(0, word.x-pad), max(0, word.y-pad)
                    right, bottom = min(width, word.x+word.width+pad), min(height, word.y+word.height+pad)
                    if right <= x or bottom <= y:
                        continue
                    boxes.append(BlurBox(x=x/width, y=y/height, width=(right-x)/width, height=(bottom-y)/height,
                                         start=max(0, t-interval), end=min(duration, t+interval+options.hold_seconds), kind=kinds[0]))
            if reader is not None and index and index < count - 1 and not warnings:
                raise ValueError("source ended before its declared frame count")
        return BlurTrack(width=width, height=height, duration=duration, boxes=smooth(boxes), warnings=warnings)
    finally:
        capture.release()
