"""Offline integration driver. Only model responses are mocked; media I/O is real."""

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
import importlib
import json
from pathlib import Path
import time
from unittest.mock import patch

from demo.make_demo_gameplay import generate, probe


class Unavailable(Exception):
    """An unmerged module or an API requiring an explicit adapter."""


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    return value


def optional_call(module_name, names, context):
    """Call an exact legacy export with explicit arguments; propagate failures."""
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise Unavailable(f"{module_name} not merged") from exc
        raise
    # Compatibility helper for older callers: one exact export and its explicit
    # kwargs. The active demo uses Pipeline directly, without guessed signatures.
    function = getattr(module, names[0], None)
    if not callable(function):
        raise Unavailable(f"{module_name}.{names[0]}: adapter needed")
    return function(**context)



class Progress:
    def __init__(self):
        self.events = []

    @contextmanager
    def stage(self, name):
        start = time.perf_counter()
        self.events.append(dict(stage=name, status="started", seconds=0))
        record = dict(stage=name, status="completed", detail="")
        try:
            yield record
        except Exception as exc:
            record.update(status="failed", detail=str(exc))
            raise
        finally:
            record["seconds"] = round(time.perf_counter() - start, 4)
            self.events.append(record)
            print(f"[{name}] {record['status']}: {record['detail']}", flush=True)

    def optional(self, name, module, names, context):
        with self.stage(name) as record:
            try:
                return optional_call(module, names, context)
            except Unavailable as exc:
                record.update(status="skipped", detail=str(exc))
                return None


@contextmanager
def offline():
    """Defense in depth: suppress dotenv loading, SDK clients and Python networking."""
    def denied(*args, **kwargs):
        raise RuntimeError("Network/model clients are forbidden in the offline demo")
    with ExitStack() as stack:
        stack.enter_context(patch("dotenv.load_dotenv", return_value=False))
        stack.enter_context(patch("google.genai.Client", side_effect=denied))
        stack.enter_context(patch("socket.socket.connect", denied))
        stack.enter_context(patch("socket.create_connection", denied))
        yield stack


def fallback_windows(duration):
    return [dict(start=start, end=min(start + 6, duration), score=0, signals={})
            for start in range(0, int(duration), 3)]


def score_windows(candidates, truth):
    """Ground-truth oracle replacing VLM inference, not a detection quality metric."""
    clips = []
    for event in truth["events"]:
        for item in candidates:
            candidate = plain(item)
            start, end = float(candidate["start"]), float(candidate["end"])
            if start <= event["start"] and end >= event["end"]:
                lo, hi = max(start, event["start"] - .5), min(end, event["end"] + .5)
                clips.append(dict(start=lo, end=hi, start_seconds=lo, end_seconds=hi,
                                  score=event["score"], label=event["kind"],
                                  type="bad" if event["kind"] == "death" else "good",
                                  description=event["text"], caption=event["text"],
                                  reaction_label="hype", event_id=event["id"],
                                  signals=candidate.get("signals", {})))
                break
    return clips


def clean_plan(clips, budget):
    selected, remaining = [], budget
    for clip in sorted(clips, key=lambda item: -item["score"]):
        length = clip["end"] - clip["start"]
        if length <= remaining:
            selected.append(dict(source_start=clip["start"], source_end=clip["end"],
                                 video_effects=["none"], sound_effects=[], speed=1,
                                 transition_in="cut"))
            remaining -= length
        if len(selected) == 3:
            break
    if not selected:
        raise ValueError("No scored clips fit the duration budget")
    return {"segments": selected}


def legacy_plan(plan):
    """Translate the documented v2 clip interval aliases into legacy segments."""
    data = plain(plan)
    if "segments" in data:
        return data
    segments = []
    for item in data["clips"]:
        clip = plain(item)
        segments.append(dict(source_start=clip.get("source_start", clip.get("start")),
                             source_end=clip.get("source_end", clip.get("end")),
                             speed=clip.get("speed", 1), video_effects=["none"],
                             sound_effects=[], transition_in="cut"))
    # Rich v2 effects are executed by render v2 when available. The legacy shim
    # intentionally preserves timing only, and reports this limitation.
    return {"segments": segments}


def coverage(plan, truth):
    hits, offset = [], 0.0
    for segment in plan["segments"]:
        start, end = segment["source_start"], segment["source_end"]
        speed = segment.get("speed", 1)
        if start is None or end is None or not 0 <= start < end <= truth["duration"] or speed <= 0:
            raise ValueError(f"Invalid planned interval: {segment}")
        for event in truth["events"]:
            if start <= event["start"] and end >= event["end"]:
                hits.append(dict(event_id=event["id"], source_start=start, source_end=end,
                                 output_time=offset + ((event["start"] + event["end"]) / 2 - start) / speed))
        offset += (end - start) / speed
    return hits, offset


def request_json(client, method, url, **kwargs):
    response = getattr(client, method)(url, **kwargs)
    if response.status_code != 200:
        raise AssertionError(f"{method.upper()} {url}: {response.status_code} {response.get_data(as_text=True)}")
    return response.get_json()


def wait_for_job(client, store, job_id, expected, timeout=180):
    """Poll the public snapshot, then verify the durable stage checkpoint."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = request_json(client, "get", f"/api/jobs/{job_id}")
        if job["status"] in {"error", "cancelled"}:
            raise AssertionError(f"Job failed: {job['error']}")
        if job["status"] == expected:
            # Terminal state is saved just before the worker unregisters itself.
            return store.get(job_id)
        time.sleep(.02)
    raise TimeoutError(f"Job did not reach {expected}")


def run(output, duration=150, budget=12):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    progress = Progress()
    report = dict(schema_version=2, offline=True, live_calls=0, budget=budget,
                  progress=progress.events, outputs={}, limitations=[
                      "Mock provider reads fixture truth: event coverage tests plumbing, not perception.",
                      "This demo covers the integrated upload/signals/analyze/plan/render/download path.",
                      "Standalone ingest, audio AI, creative planner, reactions and social libraries are not exercised."])
    started = time.perf_counter()
    try:
        with progress.stage("generate"):
            source, truth = generate(output / "fixture", duration)
            report["ground_truth"] = truth
        with offline() as stack:
            from server.api import create_app
            from pipeline import Pipeline

            class MockVLM:
                def upload_video(self, path):
                    assert Path(path).is_file()
                    return path

                def score_windows(self, path, candidates):
                    # Signal extraction remains real; whole-video oracle supplies
                    # complete fixture beats independently of candidate recall.
                    return []

                def find_clips(self, uploaded_file, prompt):
                    return score_windows(fallback_windows(duration), truth)

                def plan_edit(self, prompt):
                    available, _ = json.JSONDecoder().raw_decode(
                        prompt.split("## Available Clips\n", 1)[1].lstrip())
                    clips = [{**c, "start": c["start_seconds"], "end": c["end_seconds"]}
                             for c in available]
                    plan = clean_plan(clips, budget)
                    plan["resolution"] = 720
                    return plan

                def close(self):
                    pass

            pipeline = Pipeline()
            stack.enter_context(patch.object(pipeline, "client", side_effect=lambda *args: MockVLM()))
            app = create_app({"TESTING": True, "WORKSPACE": str(output / "jobs"),
                              "JOB_WORKERS": 1, "RECOVER_JOBS": False}, pipeline=pipeline)
            stack.callback(app.extensions["job_queue"].close)
            store = app.extensions["job_store"]
            client = app.test_client()
            with progress.stage("upload"):
                with source.open("rb") as handle:
                    response = client.post("/api/jobs", data={"video": (handle, "gameplay.mp4")})
                assert response.status_code == 201, response.get_data(as_text=True)
                job_id = response.get_json()["job_id"]
                report["job_id"] = job_id
            with progress.stage("analyze_plan"):
                response = client.post(f"/api/jobs/{job_id}/analyze", json={
                    "max_duration": budget, "style": "clean_edit", "privacy": False})
                assert response.status_code == 202, response.get_data(as_text=True)
                job = wait_for_job(client, store, job_id, "planned")
                report.update(candidates=job["candidates"], scored_clips=job["clips"], plan=job["edit_plan"])
                hits, planned_duration = coverage(job["edit_plan"], truth)
                report.update(chosen_clips_vs_ground_truth=hits, planned_duration=planned_duration)
                assert planned_duration <= budget
                assert set(truth["top_event_ids"]) <= {hit["event_id"] for hit in hits}
            for preset in ("landscape", "vertical"):
                with progress.stage(f"render_{preset}"):
                    response = client.post(f"/api/jobs/{job_id}/render", json={
                        "preset": preset, "generate_thumbnails": False})
                    assert response.status_code == 202, response.get_data(as_text=True)
                    job = wait_for_job(client, store, job_id, "done")
                with progress.stage(f"download_{preset}"):
                    response = client.get(f"/api/jobs/{job_id}/download")
                    try:
                        assert response.status_code == 200
                        assert response.mimetype == "video/mp4"
                        payload = response.get_data()
                        assert payload == Path(job["output"]).read_bytes()
                        destination = output / f"montage_{preset}.mp4"
                        destination.write_bytes(payload)
                    finally:
                        response.close()
                    meta = probe(destination)
                    video = next(s for s in meta["streams"] if s["codec_type"] == "video")
                    assert any(s["codec_type"] == "audio" for s in meta["streams"])
                    actual_duration = float(meta["format"]["duration"])
                    assert 0 < actual_duration <= budget + .25
                    assert abs(actual_duration - planned_duration) < .3
                    expected = 16 / 9 if preset == "landscape" else 9 / 16
                    assert abs(video["width"] / video["height"] - expected) < .01
                    report["outputs"][preset] = dict(path=str(destination), duration=actual_duration,
                                                      width=video["width"], height=video["height"])
            report["backend_stages"] = job["completed"]
            report["backend_timings"] = job["timings"]
            report["status"] = "completed"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report["total_seconds"] = round(time.perf_counter() - started, 3)
        (output / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("demo_out"))
    parser.add_argument("--duration", type=float, default=150)
    parser.add_argument("--budget", type=float, default=12)
    args = parser.parse_args()
    run(args.output, args.duration, args.budget)
    print(f"Demo ready: {args.output.resolve() / 'report.json'}")


if __name__ == "__main__":
    main()
