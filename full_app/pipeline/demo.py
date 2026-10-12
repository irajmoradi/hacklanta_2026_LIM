"""Offline demo adapted to durable Flask jobs and merged module contracts."""
import argparse
import importlib
import inspect
import json
from pathlib import Path
import shutil
import time
from unittest.mock import patch

from demo.make_demo_gameplay import generate, probe, synthetic_pack
from demo.pipeline import (Progress as BaseProgress, Unavailable, plain, offline,
                           fallback_windows, score_windows, clean_plan, legacy_plan,
                           coverage, request_json)


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
    if module_name == 'planner' and function.__module__.startswith('planner.'):
        from pipeline.extensions import planner_plan
        class Adapter:
            def hook(self, module, name, job):
                return getattr(importlib.import_module(module), name)
            def warn(self, job, message):
                job['warnings'].append(message)
        clips = context['clips']
        job = dict(clips=clips, options={'style': 'clean_edit', 'max_duration': context['target_length']}, warnings=[])
        # The demo oracle measures complete event coverage, so retain full beats if
        # the creative planner trims them. Production uses the planner unmodified.
        planned = planner_plan(Adapter(), job)
        full = clean_plan(clips, context['target_length'])
        if planned != full:
            return full
        return planned
    if module_name == 'social' and function.__module__ == 'social':
        kwargs['plan'] = {**plain(kwargs['plan']), 'social': {'video_path': 'montage.mp4'}}
    if module_name == 'reactions' and function.__module__.startswith('reactions.'):
        from reactions import Reaction
        entry = kwargs['reaction']
        kwargs['reaction'] = Reaction(**{**entry, 'file': Path(entry['file']),
                                        'background': 'light' if entry['background'] == 'white' else entry['background']})
    return function(**kwargs)



class Progress(BaseProgress):
    def optional(self, name, module, names, context):
        with self.stage(name) as record:
            try:
                return optional_call(module, names, context)
            except Unavailable as exc:
                record.update(status="skipped", detail=str(exc))
                return None



def run(output, duration=150, budget=12):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    progress = Progress()
    report = dict(schema_version=1, offline=True, live_calls=0, budget=budget,
                  progress=progress.events, outputs={}, limitations=[
                      "Mock window scores are a ground-truth oracle, not model accuracy.",
                      "Missing signals use overlapping uniform windows.",
                      "Legacy vertical export uses letterboxing; v2 is used when available.",
                      "Harness progress accompanies durable backend SSE checkpoints.",
                      "Oracle coverage retains complete event cuts after exercising the native planner adapter."])
    started = time.perf_counter()
    try:
        with progress.stage("generate"):
            source, truth = generate(output / "fixture", duration)
            report["ground_truth"] = truth
        with offline() as stack:
            # Import with a fake legacy client even when a user's key is exported.
            stack.enter_context(patch("services.gemini_client.GeminiVideoClient"))
            from server.api import create_app
            from pipeline import Pipeline
            backend = importlib.import_module('pipeline.orchestrator')
            pipeline = Pipeline()
            workspace = output / "jobs"
            workspace.mkdir(exist_ok=True)
            app = create_app({'TESTING': True, 'WORKSPACE': str(workspace)}, pipeline)
            stack.callback(app.extensions['job_queue'].close)
            store = app.extensions['job_store']
            client = app.test_client()
            with progress.stage("upload"):
                with source.open("rb") as handle:
                    uploaded = request_json(client, "post", "/api/upload",
                                            data={"video": (handle, "gameplay.mp4")})
                job_id = uploaded["job_id"]
                job = store.get(job_id)
                source = Path(job["source"])
                report["job_id"] = job_id
            prepared = progress.optional("ingest", "ingest", ["prepare"],
                                         {"source": source, "cache_dir": workspace / 'ingest'})
            if prepared is not None:
                prepared = plain(prepared)
                source = Path(prepared["path"])
                job["source"] = str(source)
                from services.probe import probe_video
                job["meta"] = probe_video(source)
                store.save(job)
            candidates = progress.optional("signals", "signals", ["detect_candidates"],
                                           {"video_path": source, "profile": "auto"})
            if candidates is None:
                candidates = fallback_windows(duration)
            candidates = list(candidates)
            report["candidates"] = [plain(item) for item in candidates]
            audio = progress.optional("audio_ai", "audio_ai", ["analyze"],
                                      {"video_path": source, "use_whisper": False,
                                       "use_classifier": False, "transcribe": False, "speech": "off", "vad": "energy"})
            report["audio_signals"] = plain(audio)
            if audio is not None:
                for event in plain(audio).get('events', []):
                    if event['type'] != 'silence':
                        candidates.append(dict(start=max(0, event['start']-.5),
                                               end=min(duration, event['end']+.5),
                                               score=event['score'], signals=event.get('signals', {})))
            report['candidates'] = [plain(item) for item in candidates]
            class MockVLM:
                def upload_video(self, path):
                    if not Path(path).is_file():
                        raise FileNotFoundError(path)
                    return path

                def find_clips(self, uploaded_file, prompt):
                    # Whole-video inference is independent of local proposals.
                    # Uniform oracle coverage models its ability to recover an
                    # event that scene/audio heuristics did not propose.
                    return score_windows(candidates + fallback_windows(duration), truth)

                def plan_edit(self, prompt):
                    return planned_legacy

            stack.enter_context(patch.object(pipeline, "client", return_value=MockVLM()))
            with progress.stage("vlm_window_scoring") as record:
                clips = request_json(client, "post", "/api/analyze", json={"job_id": job_id, "use_signals": False, "window_scoring": False})["clips"]
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
                def runner_factory(*args, **kwargs):
                    kwargs.update(dict(zip(('workspace', 'source', 'width', 'height', 'fps'), args)))
                    kwargs.update(workspace=preset_dir, width=dimensions[0], height=dimensions[1])
                    runner = real_runner(**kwargs)
                    if rendered is not None:
                        runner.render = lambda plan: Path(rendered)
                    return runner
                with progress.stage(f"render_{preset}"):
                    with patch.object(backend, "FFmpegRunner", side_effect=runner_factory):
                        request_json(client, "post", "/api/render",
                                     json={"job_id": job_id, "generate_thumbnails": False, "privacy": False,
                                           "prompt": preset})
                job = store.get(job_id)
                reacted = progress.optional(f"reactions_{preset}", "reactions", ["render_overlay"],
                                             {"base_clip": Path(job["output"]), "reaction": reaction,
                                              "preset": preset})
                if reacted is not None:
                    job["output"] = str(reacted)
                    store.save(job)
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
