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
    """Check actual source event barcodes in the rendered landscape timeline."""
    report = demo_result
    result = report["outputs"]["landscape"]
    expected_colors = {"event_2": (0, 255, 0), "event_4": (255, 0, 255)}
    for hit in report["chosen_clips_vs_ground_truth"]:
        if hit["event_id"] not in expected_colors:
            continue
        pixels = ffmpeg(["-ss", hit["output_time"], "-i", result["path"],
                         "-vf", "crop=4:4:iw/2:ih-6,scale=1:1,format=rgb24",
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
