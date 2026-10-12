"""EVAL-02 offline comparison: real signals/audio/chat, deterministic mock VLM."""
import argparse
import hashlib
import itertools
import json
import math
import platform
import random
import subprocess
import time
from pathlib import Path

import numpy as np

from .dataset import load_dataset
from .runner import evaluate

NAMES = ("signals-only", "vlm-only", "signals-vlm", "fusion-audio-chat")
DEFAULTS = Path(__file__).with_name("tuned_weights.json")


def load_weights(path=DEFAULTS):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    for name in ("signals-vlm", "fusion-audio-chat"):
        weights = config[name]
        if set(weights) != {"signals", "vlm", "audio", "chat", "death_penalty", "threshold"}:
            raise ValueError("Invalid fusion weight keys")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in weights.values()):
            raise ValueError("Weights must be finite nonnegative numbers")
        if not math.isclose(sum(weights[k] for k in ("signals", "vlm", "audio", "chat")), 1):
            raise ValueError("Evidence weights must sum to one")
        if weights["threshold"] > 1:
            raise ValueError("Threshold must be <= 1")
    return config


def noise(identity, position, channel, seed, amplitude):
    key = f"{identity}|{position:.3f}|{channel}|{seed}".encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(key).digest()[:8], "big"))
    return rng.uniform(-amplitude, amplitude)


def mock_observations(path):
    """Read visible HUD barcode at 2 FPS. No manifest/annotation input.

    This is a synthetic semantic oracle with controlled errors, NOT a real VLM.
    Its code is deliberately distinct from signals.detect_candidates.
    """
    raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-i", str(path),
                          "-vf", "fps=2,crop=iw:8:0:ih-8,scale=1:1", "-an", "-pix_fmt", "rgb24",
                          "-threads", "1", "-f", "rawvideo", "pipe:1"], capture_output=True, check=True).stdout
    palette = np.array([[0, 255, 0], [255, 0, 0], [0, 255, 255], [255, 255, 0]])
    kinds = ("highlight", "death", "spectating", "distractor")
    result = []
    for i, rgb in enumerate(np.frombuffer(raw, np.uint8).reshape(-1, 3)):
        distances = np.linalg.norm(palette - rgb.astype(float), axis=1)
        if distances.min() > 100:
            continue
        kind = kinds[int(distances.argmin())]
        if result and result[-1]["kind"] == kind and result[-1]["end"] == i / 2:
            result[-1]["end"] += .5
        else:
            result.append(dict(start=i / 2, end=i / 2 + .5, kind=kind))
    return result


def overlap(a, b):
    return max(0., min(a["end"], b["end"]) - max(a["start"], b["start"]))


def semantic(window, observations, identity, seed, amplitude):
    hits = [o for o in observations if overlap(window, o) > 0]
    event = max(hits, key=lambda o: overlap(window, o), default=None)
    kind = event["kind"] if event else "background"
    base = {"highlight": .78, "death": .42, "spectating": .62, "distractor": .38, "background": .15}[kind]
    value = min(1., max(0., base + noise(identity, window["start"], "score", seed, amplitude)))
    dead = float(kind in ("death", "spectating"))
    # Approximately 20% missed death/spectator recognition, with reproducible noise.
    if noise(identity, window["start"], "veto", seed, 1) > .6:
        dead = 0.
    return value, dead


def prepare(video, seed=2026, amplitude=.30):
    from signals import detect_candidates
    from audio_ai.analyzer import analyze
    from ingest.chat import chat_signal

    path = video["path"]
    timings = {}
    started = time.perf_counter()
    candidates = detect_candidates(path, scene_backend="ffmpeg", ocr=False,
                                   pre_roll=1, post_roll=5, merge_gap=0, max_length=12)
    timings["signals"] = time.perf_counter() - started
    started = time.perf_counter()
    observations = mock_observations(path)
    timings["vlm"] = time.perf_counter() - started
    started = time.perf_counter()
    audio = analyze(path, speech="off", vad="energy", events="heuristic")
    timings["audio"] = time.perf_counter() - started
    started = time.perf_counter()
    chat = chat_signal(path.parent / "chat.json", video["duration_seconds"])
    timings["chat"] = time.perf_counter() - started
    rows = []
    for candidate in candidates:
        row = candidate.to_dict()
        row["signals"] = min(1., max(0., candidate.score / 4))
        row["vlm"], row["dead"] = semantic(row, observations, video["id"], seed, amplitude)
        audio_rows = [r for r in audio.seconds if r.start < row["end"] and r.end > row["start"]]
        row["audio"] = max((max(r.signals["audio_shout"], r.signals["audio_laugh"]) for r in audio_rows), default=0.)
        row["chat"] = min(1., sum(r["signals"]["chat_clip_it"] for r in chat if overlap(row, r)) / 5)
        rows.append(row)
    whole = []
    for event in observations:
        score, _ = semantic(event, observations, video["id"], seed + 1, amplitude)
        # Whole-video mock has independent score errors and coarser temporal grounding.
        shift = noise(video["id"], event["start"], "time", seed, 3)
        start = max(0., event["start"] + shift - 1)
        end = min(video["duration_seconds"], event["end"] + shift + 1)
        if score >= .5 and end > start:
            whole.append(dict(start=start, end=end, score=score))
    return dict(rows=rows, whole=whole, timings=timings, audio_backends=audio.backends)


def predict(features, name, weights=None):
    if name == "vlm-only":
        return features["whole"]
    if name == "signals-only":
        return [dict(start=r["start"], end=r["end"], score=r["signals"]) for r in features["rows"] if r["signals"] >= .35]
    result = []
    for row in features["rows"]:
        score = sum(weights[k] * row[k] for k in ("signals", "vlm", "audio", "chat")) - weights["death_penalty"] * row["dead"]
        if score >= weights["threshold"]:
            result.append(dict(start=row["start"], end=row["end"], score=score))
    return result


def tune(training, features):
    """Only supplied training labels influence selection; stable grid-order tie break."""
    selected, trials = {}, {}
    for name in ("signals-vlm", "fusion-audio-chat"):
        best, count = None, 0
        for signal, audio, chat, penalty, threshold in itertools.product(
                (.2, .4, .6), (0.,) if name == "signals-vlm" else (.1, .2),
                (0.,) if name == "signals-vlm" else (.1, .2), (.2, .5, .8), (.35, .45, .55)):
            vlm = round(1 - signal - audio - chat, 6)
            if vlm < .1:
                continue
            weights = dict(signals=signal, vlm=vlm, audio=audio, chat=chat, death_penalty=penalty, threshold=threshold)
            output = evaluate(training, {name: lambda v: dict(clips=predict(features[v["id"]], name, weights), cost_usd=0)})
            summary = output["pipelines"][name]["summary"]
            objective = sum(summary["thresholds"][t]["f1"] for t in ("0.3", "0.5")) / 2
            count += 1
            if best is None or objective > best[0]:
                best = objective, weights
        selected[name] = best[1]
        trials[name] = dict(trials=count, train_mean_f1=best[0])
    return selected, trials


def run(manifest, output, seed=2026, amplitude=.30, weights_path=None):
    if not math.isfinite(amplitude) or not 0 <= amplitude <= 1:
        raise ValueError("noise must be between zero and one")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset(manifest)
    metadata = {v["id"]: v for v in json.loads(Path(manifest).read_text())["videos"]}
    train = [v for v in dataset if metadata[v["id"]]["split"] == "train"]
    test = [v for v in dataset if metadata[v["id"]]["split"] == "test"]
    if len(train) != len(test) or len(train) < 3 or len(train) + len(test) != len(dataset):
        raise ValueError("Require equal nonempty halves, >=6 videos")
    features = {}
    for video in dataset:
        features[video["id"]] = prepare(video, seed, amplitude)
        print(f"prepared {video['id']}", flush=True)
    weights, tuning = tune(train, features) if weights_path is None else (load_weights(weights_path), {})
    report = evaluate(test, {name: (lambda v, n=name: dict(clips=predict(features[v["id"]], n, weights.get(n)), cost_usd=0)) for name in NAMES})
    if any(p["status"] != "ok" for p in report["pipelines"].values()):
        raise RuntimeError("Incomplete benchmark")
    for name, pipeline in report["pipelines"].items():
        for row in pipeline["videos"]:
            f = features[row["id"]]
            components = (["signals"] if name == "signals-only" else ["vlm"] if name == "vlm-only" else
                          ["signals", "vlm"] if name == "signals-vlm" else ["signals", "vlm", "audio", "chat"])
            row["elapsed_seconds"] += sum(f["timings"][c] for c in components)
            row["time_to_first_clip_seconds"] = row["elapsed_seconds"] if row["predictions"] else None
            forbidden = metadata[row["id"]]["forbidden"]
            row["forbidden_picks"] = sum(any(overlap(p, f) > 0 for f in forbidden) for p in row["predictions"])
            for kind in ("death", "spectating"):
                row[kind + "_picks"] = sum(any(overlap(p, f) > 0 for f in forbidden if f["kind"] == kind) for p in row["predictions"])
            # Explicit illustrative accounting model; no provider pricing claims.
            seconds = (row["duration_seconds"] if name == "vlm-only" else
                       sum(r["end"] - r["start"] for r in f["rows"])) if name != "signals-only" else 0
            calls = (1 if name == "vlm-only" else len(f["rows"])) if name != "signals-only" else 0
            row["estimated_input_tokens"] = seconds * 100 + calls * 200
            row["estimated_output_tokens"] = calls * 100
            row["estimated_api_usd"] = (row["estimated_input_tokens"] * .30 + row["estimated_output_tokens"] * 2.50) / 1e6
        from .metrics import summarize
        summary = summarize(pipeline["videos"])
        minutes = sum(v["duration_seconds"] for v in test) / 60
        for field in ("forbidden_picks", "death_picks", "spectating_picks"):
            summary[field] = sum(r[field] for r in pipeline["videos"])
        summary["prediction_count"] = sum(r["prediction_count"] for r in pipeline["videos"])
        summary["seconds_per_footage_minute"] = sum(r["elapsed_seconds"] for r in pipeline["videos"]) / minutes
        summary["estimated_api_usd_per_minute"] = sum(r["estimated_api_usd"] for r in pipeline["videos"]) / minutes
        pipeline["summary"] = summary
    report.update(mode="synthetic-mock-vlm", seed=seed, noise_amplitude=amplitude,
                  train_ids=[v["id"] for v in train], test_ids=[v["id"] for v in test], weights=weights, tuning=tuning,
                  environment=dict(python=platform.python_version(), platform=platform.platform()),
                  cost_assumptions=dict(input_tokens_per_second=100, input_tokens_per_call=200,
                                        output_tokens_per_call=100, input_usd_per_million=.30, output_usd_per_million=2.50),
                  timing_note="Component wall times plus scoring; shared extraction measured once and charged to each applicable pipeline. Mock scans full media even for windows. Excludes generation/tuning. No inference/network latency.")
    for filename, payload in (("report.json", report), ("tuned_weights.json", weights), ("features.json", features)):
        (output / filename).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps({n: p["summary"] for n, p in report["pipelines"].items()}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--noise", type=float, default=.30)
    parser.add_argument("--weights", type=Path, help="Load frozen JSON weights instead of tuning")
    args = parser.parse_args()
    run(args.manifest, args.output, args.seed, args.noise, args.weights)
