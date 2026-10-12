"""Offline integration driver. Only model responses are mocked; media I/O is real."""

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
import importlib
import inspect
import json
from pathlib import Path
import shutil
import time
from unittest.mock import patch

from demo.make_demo_gameplay import generate, probe, synthetic_pack


class Unavailable(Exception):
    """An unmerged module or an API requiring an explicit adapter."""


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    return value


def optional_call(module_name, names, context):
    """Bind documented names/aliases, never swallow failures in an installed module."""
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise Unavailable(f"{module_name} not merged") from exc
        raise
    function = next((getattr(module, name) for name in names
                     if callable(getattr(module, name, None))), None)
    if function is None:
        raise Unavailable(f"{module_name}: expected export {' / '.join(names)}; adapter needed")
    signature = inspect.signature(function)
    kwargs = {name: context[name] for name, p in signature.parameters.items()
              if name in context and p.kind != p.POSITIONAL_ONLY}
    try:
        signature.bind(**kwargs)
    except TypeError as exc:
        raise Unavailable(f"{module_name}.{function.__name__}{signature}: adapter needed ({exc})") from exc
    return function(**kwargs)


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


def run(output, duration=150, budget=12):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    progress = Progress()
    report = dict(schema_version=1, offline=True, live_calls=0, budget=budget,
                  progress=progress.events, outputs={}, limitations=[
                      "Mock window scores are a ground-truth oracle, not model accuracy.",
                      "Missing signals use overlapping uniform windows.",
                      "Legacy vertical export uses letterboxing; v2 is used when available.",
                      "Progress is emitted by the harness; legacy backend has no SSE."])
    started = time.perf_counter()
    try:
        with progress.stage("generate"):
            source, truth = generate(output / "fixture", duration)
            report["ground_truth"] = truth
        with offline() as stack:
            # Import with a fake legacy client even when a user's key is exported.
            stack.enter_context(patch("services.gemini_client.GeminiVideoClient"))
            backend = importlib.import_module("app")
            workspace = output / "jobs"
            workspace.mkdir(exist_ok=True)
            stack.enter_context(patch.object(backend, "WORKSPACE", workspace))
            stack.enter_context(patch.object(backend, "jobs", {}))
            client = backend.app.test_client()
            with progress.stage("upload"):
                with source.open("rb") as handle:
                    uploaded = request_json(client, "post", "/api/upload",
                                            data={"video": (handle, "gameplay.mp4")})
                job_id = uploaded["job_id"]
                job = backend.jobs[job_id]
                source = Path(job["source"])
                report["job_id"] = job_id
            prepared = progress.optional("ingest", "ingest", ["prepare"], {"source": source})
            if prepared is not None:
                prepared = plain(prepared)
                source = Path(prepared["path"])
                job["source"] = str(source)
                job["meta"] = backend.probe_video(source)
            candidates = progress.optional("signals", "signals", ["detect_candidates"],
                                           {"video_path": source, "profile": "auto"})
            if candidates is None:
                candidates = fallback_windows(duration)
            candidates = list(candidates)
            report["candidates"] = [plain(item) for item in candidates]
            audio = progress.optional("audio_ai", "audio_ai", ["analyze"],
                                      {"video_path": source, "use_whisper": False,
                                       "use_classifier": False, "transcribe": False})
            report["audio_signals"] = plain(audio)
            class MockVLM:
                def upload_video(self, path):
                    if not Path(path).is_file():
                        raise FileNotFoundError(path)
                    return path

                def find_clips(self, uploaded_file, prompt):
                    return score_windows(candidates, truth)

                def plan_edit(self, prompt):
                    return planned_legacy

            stack.enter_context(patch.object(backend, "_get_gemini", return_value=MockVLM()))
            with progress.stage("vlm_window_scoring") as record:
                clips = request_json(client, "post", "/api/analyze", json={"job_id": job_id})["clips"]
                record["detail"] = "Mocked VLM scores through real /api/analyze"
                report["scored_clips"] = clips
            native_plan = progress.optional("planner_v2", "planner", ["plan_edit", "build_plan", "plan"],
                                            {"clips": clips, "ranked_clips": clips, "mode": "nice",
                                             "style": "clean_edit", "target_length": budget,
                                             "target_duration": budget, "max_duration": budget,
                                             "aspect": "landscape", "audio_signals": audio,
                                             "use_llm": False, "refine": False})
            planned_legacy = legacy_plan(native_plan) if native_plan is not None else clean_plan(clips, budget)
            with progress.stage("planner") as record:
                planned_legacy = request_json(client, "post", "/api/plan",
                                             json={"job_id": job_id, "max_duration": budget,
                                                   "edit_style": "clean_edit"})["edit_plan"]
                report["plan"] = plain(native_plan) if native_plan is not None else planned_legacy
                hits, planned_duration = coverage(planned_legacy, truth)
                report.update(chosen_clips_vs_ground_truth=hits, planned_duration=planned_duration)
                assert planned_duration <= budget, "Planner exceeded budget"
                assert set(truth["top_event_ids"]) <= {hit["event_id"] for hit in hits}, "Top events lost"
                record["detail"] = "v2 plan via legacy API" if native_plan is not None else "Deterministic clean-edit fallback via mocked plan response"
            reaction = synthetic_pack(output / "synthetic_pack")
            real_runner = backend.FFmpegRunner
            for preset, dimensions in [("landscape", (640, 360)), ("vertical", (360, 640))]:
                preset_dir = Path(job["dir"]) / preset
                preset_dir.mkdir(exist_ok=True)
                rendered = progress.optional(f"render_v2_{preset}", "render", ["render_plan", "render"],
                                             {"source": source, "video_path": source,
                                              "plan": native_plan if native_plan is not None else planned_legacy,
                                              "preset": preset, "output_path": preset_dir / "v2.mp4",
                                              "workspace": preset_dir})
                def runner_factory(**kwargs):
                    kwargs.update(workspace=preset_dir, width=dimensions[0], height=dimensions[1])
                    runner = real_runner(**kwargs)
                    if rendered is not None:
                        runner.render = lambda plan: Path(rendered)
                    return runner
                with progress.stage(f"render_{preset}"):
                    with patch.object(backend, "FFmpegRunner", side_effect=runner_factory):
                        request_json(client, "post", "/api/render",
                                     json={"job_id": job_id, "generate_thumbnails": False})
                reacted = progress.optional(f"reactions_{preset}", "reactions", ["render_overlay"],
                                             {"base_clip": Path(job["output"]), "reaction": reaction,
                                              "preset": preset})
                if reacted is not None:
                    job["output"] = str(reacted)
                # Keep a conventional final artifact next to the job metadata for social.
                shutil.copyfile(job["output"], preset_dir / "montage.mp4")
                share = progress.optional(f"social_{preset}", "social", ["build_share_kit"],
                                          {"job_dir": preset_dir, "clips": clips,
                                           "plan": native_plan if native_plan is not None else planned_legacy,
                                           "game": "generic"})
                if share is not None:
                    assert Path(share).exists(), "Share kit was not created"
                with progress.stage(f"download_{preset}"):
                    response = client.get(f"/api/download/{job_id}")
                    try:
                        assert response.status_code == 200
                        assert response.mimetype == "video/mp4"
                        payload = response.get_data()
                        assert payload == Path(job["output"]).read_bytes(), "Download differs from render"
                        destination = output / f"montage_{preset}.mp4"
                        destination.write_bytes(payload)
                    finally:
                        response.close()
                    meta = probe(destination)
                    streams = meta["streams"]
                    video = next(stream for stream in streams if stream["codec_type"] == "video")
                    assert any(stream["codec_type"] == "audio" for stream in streams)
                    actual_duration = float(meta["format"]["duration"])
                    assert 0 < actual_duration <= budget + .25
                    assert abs(actual_duration - planned_duration) < .3, "Rendered timeline drifted"
                    assert abs(video["width"] / video["height"] - dimensions[0] / dimensions[1]) < .01
                    report["outputs"][preset] = dict(path=str(destination), duration=actual_duration,
                                                      width=video["width"], height=video["height"],
                                                      share_kit=str(share) if share else None)
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
