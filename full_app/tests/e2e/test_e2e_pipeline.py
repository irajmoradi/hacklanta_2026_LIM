"""Real media and Flask routes, with deterministic mocked model responses."""

import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from demo.make_demo_gameplay import events_for, ffmpeg, generate, probe
from demo.pipeline import (Progress, Unavailable, clean_plan, coverage, fallback_windows,
                           legacy_plan, offline, optional_call, run, score_windows)


@pytest.fixture(scope="module")
def demo_result(tmp_path_factory):
    output = tmp_path_factory.mktemp("e2e demo")
    return run(output, duration=28, budget=8)


@pytest.mark.slow
def test_pipeline(demo_result):
    report = demo_result
    assert report["status"] == "completed"
    assert report["live_calls"] == 0
    assert report["total_seconds"] < 300
    truth = report["ground_truth"]
    hits = report["chosen_clips_vs_ground_truth"]
    assert set(truth["top_event_ids"]) <= {item["event_id"] for item in hits}
    required = {"generate", "upload", "ingest", "signals", "audio_ai", "vlm_window_scoring",
                "planner_v2", "planner"}
    required |= {f"{stage}_{preset}" for stage in ["render_v2", "render", "reactions", "social", "download"]
                 for preset in ["landscape", "vertical"]}
    assert {entry["stage"] for entry in report["progress"]} == required
    for stage in required:
        entries = [entry for entry in report["progress"] if entry["stage"] == stage]
        assert len(entries) == 2
        assert entries[0]["status"] == "started"
        assert entries[1]["status"] in {"completed", "skipped"}
        assert entries[1]["seconds"] >= 0
        if entries[1]["status"] == "skipped":
            assert entries[1]["detail"]
    for preset, result in report["outputs"].items():
        path = Path(result["path"])
        assert path.stat().st_size > 1000
        meta = probe(path)
        assert float(meta["format"]["duration"]) <= report["budget"] + .25
        assert {stream["codec_type"] for stream in meta["streams"]} >= {"video", "audio"}
        assert result["width"] > result["height"] if preset == "landscape" else result["width"] < result["height"]
        # Decode every frame: existence/ffprobe alone can miss a truncated montage.
        ffmpeg(["-i", path, "-f", "null", "-"])
    saved = json.loads((Path(report["outputs"]["landscape"]["path"]).parent / "report.json").read_text())
    assert saved == report


@pytest.mark.slow
def test_top_events_are_in_encoded_pixels(demo_result):
    """Check actual source event barcodes in both encoded output timelines."""
    report = demo_result
    expected_colors = {"event_2": (0, 255, 0), "event_4": (255, 0, 255)}
    for preset, result in report["outputs"].items():
        is_legacy = any(entry["stage"] == f"render_v2_{preset}" and entry["status"] == "skipped"
                        for entry in report["progress"])
        y = result["height"] - 6
        if preset == "vertical" and is_legacy:
            # The legacy renderer pads a downscaled 16:9 image into a 9:16 frame.
            active_height = int(result["width"] * 9 / 16) // 2 * 2
            y = (result["height"] + active_height) // 2 - 3
        for hit in report["chosen_clips_vs_ground_truth"]:
            if hit["event_id"] not in expected_colors:
                continue
            pixels = ffmpeg(["-ss", hit["output_time"], "-i", result["path"],
                             "-vf", f"crop=2:2:iw/2:{y},scale=1:1,format=rgb24",
                             "-frames:v", "1", "-f", "rawvideo", "-"])
            assert len(pixels) == 3
            assert max(abs(actual - expected) for actual, expected in
                       zip(pixels, expected_colors[hit["event_id"]])) < 45


def test_oracle_budget_and_coverage():
    truth = {"duration": 150, "events": events_for(150)}
    clips = score_windows(fallback_windows(150), truth)
    plan = clean_plan(clips, 8)
    hits, duration = coverage(plan, truth)
    assert duration <= 8
    assert {"event_2", "event_4"} <= {item["event_id"] for item in hits}
    assert len({clip["event_id"] for clip in clips}) == 6
    with pytest.raises(ValueError, match="budget"):
        clean_plan(clips, .1)
    with pytest.raises(ValueError, match="Invalid"):
        coverage({"segments": [{"source_start": 0, "source_end": 151}]}, truth)
    assert legacy_plan({"clips": [{"start": 1, "end": 2}]})["segments"][0]["source_start"] == 1


def test_missing_module_reports_skip():
    progress = Progress()
    assert progress.optional("missing", "ext16_not_merged", ["prepare"], {}) is None
    assert progress.events[-1]["status"] == "skipped"
    assert "not merged" in progress.events[-1]["detail"]


@pytest.mark.parametrize("module_name,export,context", [
    ("ingest", "prepare", {"source": "video.mp4"}),
    ("signals", "detect_candidates", {"video_path": "video.mp4", "profile": "auto"}),
    ("audio_ai", "analyze", {"video_path": "video.mp4"}),
    ("planner", "build_plan", {"clips": []}),
    ("render", "render_plan", {"plan": {}}),
    ("reactions", "render_overlay", {"base_clip": "video.mp4", "reaction": {}, "preset": "vertical"}),
    ("social", "build_share_kit", {"job_dir": ".", "clips": [], "plan": {}, "game": "generic"}),
])
def test_optional_module_dispatch(monkeypatch, module_name, export, context):
    module = ModuleType(module_name)
    # Use an explicit signature: real adapters must supply all required args.
    import inspect
    received = {}
    def function(**kwargs):
        received.update(kwargs)
        return "ran"
    function.__signature__ = inspect.Signature([
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY) for name in context])
    setattr(module, export, function)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert optional_call(module_name, [export], context) == "ran"
    assert received == context


def test_installed_module_errors_are_not_skips(monkeypatch):
    module = ModuleType("ext16_broken")
    def broken(source):
        raise ValueError("real regression")
    module.prepare = broken
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ValueError, match="real regression"):
        optional_call(module.__name__, ["prepare"], {"source": "video"})
    with pytest.raises(Unavailable, match="adapter needed"):
        optional_call(module.__name__, ["prepare"], {})
    def missing_dependency(source):
        raise ModuleNotFoundError("dependency broken", name="optional_dependency")
    module.prepare = missing_dependency
    with pytest.raises(ModuleNotFoundError):
        optional_call(module.__name__, ["prepare"], {"source": "video"})


def test_offline_blocks_sdk_even_with_exported_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    from google import genai
    with offline():
        with pytest.raises(RuntimeError, match="forbidden"):
            genai.Client(api_key="not-a-real-key")


@pytest.mark.parametrize("duration", [0, 13, 181, float("nan")])
def test_generator_rejects_invalid_duration(tmp_path, duration):
    with pytest.raises(ValueError):
        generate(tmp_path, duration)


def test_failure_still_writes_progress_report(tmp_path):
    with pytest.raises(ValueError):
        run(tmp_path, duration=0)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["progress"][-1]["stage"] == "generate"
    assert report["progress"][-1]["status"] == "failed"


@pytest.mark.slow
def test_optional_stages_chain_when_modules_land(tmp_path, monkeypatch):
    """Contract stand-ins test orchestration, not unmerged module implementations."""
    import shutil
    from services.ffmpeg_runner import FFmpegRunner

    calls = []
    def install(name, export, function):
        module = ModuleType(name)
        setattr(module, export, function)
        monkeypatch.setitem(sys.modules, name, module)

    def prepare(source):
        destination = Path(source).with_name("prepared.mp4")
        shutil.copyfile(source, destination)
        calls.append("ingest")
        return {"path": destination}

    def detect_candidates(video_path, profile):
        assert Path(video_path).name == "prepared.mp4"
        calls.append("signals")
        return fallback_windows(28)

    def analyze(video_path, transcribe=True):
        assert not transcribe
        calls.append("audio_ai")
        return {"events": [], "signals": {"voice": [0.1]}}

    def build_plan(ranked_clips, target_length, audio_signals, use_llm=True):
        assert audio_signals["signals"]["voice"] == [0.1]
        assert not use_llm
        calls.append("planner")
        return {"clips": [{"start": segment["source_start"], "end": segment["source_end"]}
                          for segment in clean_plan(ranked_clips, target_length)["segments"]]}

    def render_plan(source, plan, preset, workspace):
        assert "clips" in plan
        width, height = (640, 360) if preset == "landscape" else (360, 640)
        calls.append(f"render_{preset}")
        return FFmpegRunner(workspace, source, width, height, 15).render(legacy_plan(plan))

    def render_overlay(base_clip, reaction, preset):
        assert Path(reaction["file"]).is_file()
        assert reaction["speaker"] == "Tone Bot"
        calls.append(f"reactions_{preset}")
        # Contract-only stand-in: real overlay implementation is not merged.
        output = Path(base_clip).with_name("reacted.mp4")
        shutil.copyfile(base_clip, output)
        return output

    def build_share_kit(job_dir, clips, plan, game):
        assert (job_dir / "montage.mp4").exists()
        assert clips and plan and game == "generic"
        calls.append(f"social_{job_dir.name}")
        share = job_dir / "share"
        share.mkdir()
        shutil.copyfile(job_dir / "montage.mp4", share / "video.mp4")
        return share

    for name, export, function in [
        ("ingest", "prepare", prepare), ("signals", "detect_candidates", detect_candidates),
        ("audio_ai", "analyze", analyze), ("planner", "build_plan", build_plan),
        ("render", "render_plan", render_plan), ("reactions", "render_overlay", render_overlay),
        ("social", "build_share_kit", build_share_kit),
    ]:
        install(name, export, function)
    report = run(tmp_path, duration=28, budget=8)
    assert calls == ["ingest", "signals", "audio_ai", "planner", "render_landscape",
                     "reactions_landscape", "social_landscape", "render_vertical",
                     "reactions_vertical", "social_vertical"]
    assert all(entry["status"] in {"started", "completed"} for entry in report["progress"])
    assert all(Path(result["share_kit"]).is_dir() for result in report["outputs"].values())
