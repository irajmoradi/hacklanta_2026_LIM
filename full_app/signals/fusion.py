"""Per-second normalization, local maxima, bounded windows and dead-air trim."""

import math
import numpy as np

from .models import Candidate


def zscore(values):
    values = np.asarray(values, dtype=float)
    std = values.std() if len(values) else 0
    return (values - values.mean()) / std if std > 1e-8 else np.zeros_like(values)


def fuse(raw, events, duration, cfg):
    normalized = {key: zscore(value) for key, value in raw.items()}
    curve = sum(cfg.weights[key] * values for key, values in normalized.items())
    dead = ((raw["motion"] < cfg.dead_motion) & (raw["rms"] < cfg.dead_audio)
            & (raw["ocr"] == 0) & (raw["scene"] == 0))
    # One representative peak per plateau; never nominate silent/static seconds.
    peaks = [i for i, value in enumerate(curve)
             if not dead[i] and value > cfg.peak_threshold
             and (i == 0 or value > curve[i - 1])
             and (i == len(curve) - 1 or value >= curve[i + 1])]
    windows = []
    for i in peaks:
        start, end = max(0., i - cfg.pre_roll), min(duration, i + 1 + cfg.post_roll)
        if windows and start <= windows[-1][1] + cfg.merge_gap:
            windows[-1][1] = max(end, windows[-1][1])
        else:
            windows.append([start, end])
    bounded = []
    for start, end in windows:
        if cfg.trim_dead_air:
            while start + 1 < end and dead[int(start)]:
                start = math.floor(start) + 1.
            while end - 1 > start and dead[min(len(dead) - 1, math.ceil(end) - 1)]:
                end = math.ceil(end) - 1.
        if end - start < cfg.min_length:
            center = (start + end) / 2
            start = max(0., min(center - cfg.min_length / 2, duration - cfg.min_length))
            end = min(duration, start + cfg.min_length)
        # Partition long merged action so later peaks are retained. Equal pieces
        # avoid an undersized tail; impossible min/max combinations drop the gap.
        pieces = max(1, math.ceil((end - start) / cfg.max_length))
        size = (end - start) / pieces
        if size < cfg.min_length and pieces > 1:
            for peak in sorted((p for p in peaks if start <= p < end),
                               key=lambda p: (-curve[p], p)):
                left = max(start, min(peak - cfg.pre_roll, end - cfg.max_length))
                right = min(end, left + cfg.max_length)
                if not any(left < b and right > a for a, b in bounded):
                    bounded.append((left, right))
        else:
            bounded.extend((start + j * size, start + (j + 1) * size) for j in range(pieces))
    # Minimum-length expansion can cause overlaps. Keep the stronger candidate.
    candidates = []
    for start, end in bounded:
        lo, hi = int(start), min(len(curve), math.ceil(end))
        if hi <= lo or not any(start <= min(duration - 1e-9, p + .5) < end for p in peaks):
            continue
        candidates.append(Candidate(
            round(start, 3), round(end, 3), round(float(curve[lo:hi].max()), 6),
            {key: round(float(value[lo:hi].max()), 6) for key, value in normalized.items()},
            [event for event in events if event["time"] < end
             and (event["time"] >= start or event.get("end", event["time"]) > start)],
        ))
    ranked = []
    for candidate in sorted(candidates, key=lambda c: (-c.score, c.start)):
        if not any(candidate.start < c.end and candidate.end > c.start for c in ranked):
            ranked.append(candidate)
    return ranked[:cfg.max_candidates]
