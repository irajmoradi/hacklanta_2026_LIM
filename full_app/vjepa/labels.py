"""Normalize Candidate.events and explicit pairwise/keep-drop supervision."""
import json
import math
from pathlib import Path


def weak_labels(candidates_json):
    """Accept JSON text, a JSON path, a Candidate list, or an envelope with preferences."""
    if isinstance(candidates_json, Path):
        candidates_json = json.loads(candidates_json.read_text())
    elif isinstance(candidates_json, str):
        candidates_json = json.loads(candidates_json)
    envelope = candidates_json if isinstance(candidates_json, dict) else {"candidates": candidates_json}
    labels, ids, edits = [], set(), {}
    for index, candidate in enumerate(envelope.get("candidates", [])):
        if hasattr(candidate, "model_dump"):
            candidate = candidate.model_dump()
        start, end = float(candidate["start"]), float(candidate["end"])
        if not math.isfinite(start + end) or start < 0 or end <= start:
            raise ValueError("invalid candidate bounds")
        identifier = str(candidate.get("id", index))
        if identifier in ids:
            raise ValueError("duplicate candidate id")
        ids.add(identifier)
        events = []
        for event in candidate.get("events", []):
            if hasattr(event, "model_dump"):
                event = event.model_dump()
            if isinstance(event, str):
                event = {"type": event}
            kind = event.get("type", event.get("kind"))
            if kind not in ("kill", "death"):
                continue
            time = event.get("time", event.get("timestamp", event.get("start")))
            if time is not None:
                time = float(time)
                if not math.isfinite(time) or not start <= time < end:
                    continue
            events.append({"type": kind, "time": time})
        labels.append({"id": identifier, "start": start, "end": end, "events": events})
        if candidate.get("decision") in ("keep", "drop"):
            edits[identifier] = candidate["decision"]
    pairs = []
    for pair in envelope.get("preferences", []):
        winner, loser = str(pair["winner"]), str(pair["loser"])
        if winner not in ids or loser not in ids or winner == loser:
            raise ValueError("preference must reference two distinct candidate ids")
        pairs.append((winner, loser))
    pairs.extend((a, b) for a in edits for b in edits if edits[a] == "keep" and edits[b] == "drop")
    # Window-level weak classes; mixed events prefer death, a deterministic documented policy.
    for label in labels:
        kinds = {event["type"] for event in label["events"]}
        label["label"] = "death" if "death" in kinds else "kill" if "kill" in kinds else "none"
    return {"windows": labels, "preferences": sorted(set(pairs))}


def align_labels(bounds, labels):
    """Ignore unannotated windows (-1); no-event annotated regions are weak negatives."""
    result = []
    for start, end in bounds:
        covered, kinds = False, set()
        for label in labels["windows"]:
            if max(start, label["start"]) >= min(end, label["end"]):
                continue
            covered |= label["start"] <= start and label["end"] >= end
            for event in label["events"]:
                if event["time"] is None or start <= event["time"] < end:
                    kinds.add(event["type"])
        result.append(2 if "death" in kinds else 1 if "kill" in kinds else 0 if covered else -1)
    return result
