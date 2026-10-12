"""Compare pipelines, preserving skips/errors and unknown accounting values."""

import argparse
import json
import time
from pathlib import Path

from .dataset import load_dataset
from .metrics import detection_metrics, interval, number, summarize
from .pipelines import GeminiOnly, Unavailable, mock_pipeline, optional_function, signals_only, signals_vlm

NAMES = ("gemini-only", "signals-only", "signals-vlm")


def evaluate(dataset, pipelines, clock=time.perf_counter):
    report = {"version": 1, "pipelines": {}}
    for name, pipeline in pipelines.items():
        rows, skipped, errors = [], [], []
        for video in dataset:
            try:
                # Labels are never passed into prediction adapters.
                inputs = {k: v for k, v in video.items() if k != "highlights"}
                started = clock()
                output = pipeline(inputs)
                elapsed = clock() - started
                if isinstance(output, list):
                    output = {"clips": output}
                clips = [interval(c, video["duration_seconds"]) for c in output["clips"]]
                cost = output.get("cost_usd")
                if cost is not None:
                    cost = number(cost, "cost_usd", 0)
                first = output.get("time_to_first_clip_seconds", elapsed) if clips else None
                if first is not None:
                    first = number(first, "time_to_first_clip_seconds", 0)
                    if first > elapsed:
                        raise ValueError("Time to first clip exceeds measured pipeline latency")
                rows.append({"id": video["id"], "duration_seconds": video["duration_seconds"],
                             "label_count": len(video["highlights"]), "prediction_count": len(clips),
                             "predictions": clips, "elapsed_seconds": elapsed,
                             "time_to_first_clip_seconds": first, "cost_usd": cost,
                             "cost_usd_per_minute": cost * 60 / video["duration_seconds"] if cost is not None else None,
                             "metrics": {str(t): detection_metrics(clips, video["highlights"], t)
                                         for t in (0.3, 0.5)}})
            except Unavailable as exc:
                skipped.append({"id": video["id"], "reason": str(exc)})
            except Exception as exc:
                # Do not serialize provider exception messages: they may contain credentials.
                errors.append({"id": video["id"], "error": type(exc).__name__})
        report["pipelines"][name] = {
            "status": "error" if errors else "partial" if rows and skipped else "ok" if rows else "skipped",
            "summary": summarize(rows), "videos": rows, "skipped": skipped, "errors": errors}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="CI synthetic fixtures only")
    mode.add_argument("--replay", type=Path, help="Recorded outputs: {pipeline: {video_id: output}}")
    mode.add_argument("--live-smoke", action="store_true", help="Allow <=3 legacy Gemini generation calls")
    parser.add_argument("--window-scorer", help="Trusted local/mock module:function(video_path, candidates)")
    args = parser.parse_args(argv)
    dataset = load_dataset(args.manifest)
    if args.live_smoke and len(dataset) > 3:
        parser.error("Live smoke datasets must contain at most 3 videos")
    if args.mock:
        pipelines = {name: mock_pipeline(name) for name in NAMES}
    elif args.replay:
        recorded = json.loads(args.replay.read_text(encoding="utf-8"))
        def replay(name):
            def predict(video):
                if video["id"] not in recorded.get(name, {}):
                    raise Unavailable("No recorded output for this pipeline/video")
                output = dict(recorded[name][video["id"]])
                # Historical timing is not measured latency of this replay run.
                output.pop("time_to_first_clip_seconds", None)
                return output
            return predict
        pipelines = {name: replay(name) for name in NAMES}
    else:
        scorer = None
        if args.window_scorer:
            module, name = args.window_scorer.split(":", 1)
            scorer = optional_function(module, name)
        pipelines = {"gemini-only": GeminiOnly(args.live_smoke), "signals-only": signals_only,
                     "signals-vlm": lambda video: signals_vlm(video, scorer)}
    report = evaluate(dataset, pipelines)
    report["mode"] = "mock" if args.mock else "replay" if args.replay else "live-smoke" if args.live_smoke else "offline"
    report["timing_note"] = "Wall time to returned clips, including upload/preprocessing; replay measures replay overhead."
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return int(any(p["errors"] for p in report["pipelines"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
