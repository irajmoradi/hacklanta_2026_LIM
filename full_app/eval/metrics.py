"""One-to-one temporal detection metrics with confidence-ranked matching."""

import math


def number(value, name, minimum=None):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f"Invalid {name}: {value}")
    return value


def interval(item, duration=None):
    """Accept canonical intervals and existing application clip dictionaries."""
    if hasattr(item, "model_dump"):
        item = item.model_dump()
    start = number(item.get("start_seconds", item.get("start")), "start", 0)
    end = number(item.get("end_seconds", item.get("end")), "end", 0)
    if end <= start or (duration is not None and end > duration):
        raise ValueError("Intervals must satisfy 0 <= start < end <= duration")
    return {"start": start, "end": end,
            "score": number(item.get("score", item.get("hype", 1)), "score")}


def temporal_iou(a, b):
    a, b = interval(a), interval(b)
    intersection = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return intersection / (a["end"] - a["start"] + b["end"] - b["start"] - intersection)


def detection_metrics(predictions, truth, threshold):
    """Greedy best-unmatched IoU matching, stable descending confidence order.

    AP uses the all-points precision envelope (not 11-point interpolation).
    Empty denominators produce zero, including AP for negative-only videos.
    """
    threshold = number(threshold, "threshold", 0)
    if threshold > 1:
        raise ValueError("threshold must be <= 1")
    predictions = sorted(map(interval, predictions), key=lambda x: -x["score"])
    truth = list(map(interval, truth))
    matched, flags = set(), []
    for prediction in predictions:
        candidates = [(temporal_iou(prediction, target), i)
                      for i, target in enumerate(truth) if i not in matched]
        overlap, index = max(candidates, default=(-1, -1))
        hit = overlap >= threshold
        if hit:
            matched.add(index)
        flags.append(int(hit))
    tp = sum(flags)
    precision = tp / len(predictions) if predictions else 0.0
    recall = tp / len(truth) if truth else 0.0
    cumulative, precisions = 0, []
    for rank, hit in enumerate(flags, 1):
        cumulative += hit
        precisions.append(cumulative / rank)
    envelope, ap = 0.0, 0.0
    for hit, p in zip(reversed(flags), reversed(precisions)):
        envelope = max(envelope, p)
        ap += hit * envelope
    return {"tp": tp, "fp": len(predictions) - tp, "fn": len(truth) - tp,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "ap": ap / len(truth) if truth else 0.0}


def summarize(rows):
    """Micro P/R/F1; macro AP over videos with labels; total-cost/total-minutes."""
    result = {"videos": len(rows), "thresholds": {}}
    for threshold in ("0.3", "0.5"):
        tp, fp, fn = (sum(row["metrics"][threshold][key] for row in rows)
                      for key in ("tp", "fp", "fn"))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        aps = [row["metrics"][threshold]["ap"] for row in rows if row["label_count"]]
        result["thresholds"][threshold] = {
            "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "mAP": sum(aps) / len(aps) if aps else None}
    maps = [m["mAP"] for m in result["thresholds"].values() if m["mAP"] is not None]
    result["mAP"] = sum(maps) / len(maps) if maps else None
    times = [r["time_to_first_clip_seconds"] for r in rows
             if r["time_to_first_clip_seconds"] is not None]
    result["mean_time_to_first_clip_seconds"] = sum(times) / len(times) if times else None
    result["videos_with_clip"] = len(times)
    costs = [r["cost_usd"] for r in rows]
    minutes = sum(r["duration_seconds"] for r in rows) / 60
    result["cost_usd_per_minute"] = (sum(costs) / minutes
        if minutes and all(c is not None for c in costs) else None)
    return result
