"""EXT-29: offline safety/provider checks and real synthetic FFmpeg renders."""

from dataclasses import replace
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from roast import FailMoment, GeminiLines, plan_roasts, safe_line, video_filter
from roast.planner import LINES, TEMPLATES


@pytest.mark.parametrize("line", [line for rows in LINES.values() for line in rows])
def test_curated_lines_are_safe(line):
    assert safe_line(line)


@pytest.mark.parametrize("line", ["You are an idiot", "Aim is gay", "Aim is retarded", "Aim n1gger",
    "Aim is worthless like women", "Aim kill yourself", "Aim is bad because religion",
    "Aim is autistic", "Ａim is loading", "Aim\u200bis loading", "Aim\nloading", "Aim;movie=/etc/passwd",
    "Aim %{filename}", "Aim is loading'", "Aim " + "a" * 80, "", None, 42])
def test_rejects_personal_attacks_obfuscation_and_injection(line):
    assert not safe_line(line)


def test_mock_gemini_and_partial_fallback():
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(
        text=json.dumps(["Aim went on vacation.", "You are an idiot"])))))
    plan = plan_roasts([FailMoment(0.5, "whiff"), FailMoment(2, "death")], 4,
                       intensity=2, line_writer=GeminiLines(client, "test-model"))
    assert [o.source for o in plan.overlays] == ["gemini", "fallback"]
    assert plan.overlays[1].caption == LINES["death"][1]
    client.models.generate_content.assert_called_once()
    json.dumps(plan.to_dict())


@pytest.mark.parametrize("result", [None, {}, ["Aim is loading."] * 2, [None]])
def test_malformed_provider_falls_back(result):
    assert plan_roasts([FailMoment(0)], 1, line_writer=lambda *_: result).overlays[0].source == "fallback"


def test_provider_failure_off_and_empty():
    writer = Mock(side_effect=TimeoutError)
    assert plan_roasts([FailMoment(0)], 1, line_writer=writer).overlays[0].source == "fallback"
    writer.reset_mock()
    assert not plan_roasts([FailMoment(0)], 1, intensity=0, line_writer=writer).overlays
    assert not plan_roasts([], 1, line_writer=writer).overlays
    writer.assert_not_called()


def test_invalid_json_from_gemini():
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(
        return_value=SimpleNamespace(text="not json"))))
    plan = plan_roasts([FailMoment(0)], 1, line_writer=GeminiLines(client, "test-model"))
    assert plan.overlays[0].source == "fallback"
    client.models.generate_content.assert_called_once()


def test_timing_sorted_clamped_deduplicated():
    events = [FailMoment(1.99), FailMoment(0.501), FailMoment(0.502), FailMoment(0)]
    plan = plan_roasts(events, 2, intensity=3)
    assert len(plan.overlays) == 3
    for i, (o, b) in enumerate(zip(plan.overlays, plan.beats)):
        assert 0 <= o.start == b.start < b.end <= o.end <= 2
        assert o.start == pytest.approx(round(o.start * 30) / 30)
        if i:
            assert plan.overlays[i-1].end <= o.start
    assert plan == plan_roasts(events, 2, intensity=3)
    assert plan.sound_effects[0].sfx_key == "spongebob_fail"


def test_sound_missing_and_preferred(monkeypatch, tmp_path):
    from models.effects import SOUND_EFFECTS
    monkeypatch.setitem(SOUND_EFFECTS, "spongebob_fail", {"file": None})
    assert not plan_roasts([FailMoment(0)], 1, intensity=2).sound_effects
    asset = tmp_path / "scratch.mp3"
    asset.touch()
    monkeypatch.setitem(SOUND_EFFECTS, "record_scratch", {"file": str(asset)})
    assert plan_roasts([FailMoment(0)], 1, intensity=2).sound_effects[0].sfx_key == "record_scratch"


@pytest.mark.parametrize("kwargs", [{"duration": 0}, {"duration": float("nan")}, {"fps": 0},
    {"intensity": True}, {"intensity": 4}, {"template": "unknown"}])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        plan_roasts([], **({"duration": 2} | kwargs))


@pytest.mark.parametrize("time", [-1, float("inf"), float("nan"), True])
def test_invalid_fail(time):
    with pytest.raises(ValueError):
        FailMoment(time)


def test_out_of_bounds_and_renderer_validation():
    with pytest.raises(ValueError):
        plan_roasts([FailMoment(2)], 2)
    plan = plan_roasts([FailMoment(0)], 1)
    with pytest.raises(ValueError):
        video_filter(replace(plan, overlays=(replace(plan.overlays[0], caption="You are bad"),)))


def run(args):
    return subprocess.run([str(a) for a in args], capture_output=True, check=True, timeout=45)


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("roast") / "source.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-threads", "2",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path])
    return path


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_render_and_audio(source, tmp_path, template):
    plan = plan_roasts([FailMoment(0.5, "whiff")], 2, template=template, intensity=2)
    output = tmp_path / f"{template}.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", source, "-filter_threads", "1", "-vf", video_filter(plan),
         "-c:v", "libx264", "-threads", "2", "-c:a", "copy", output])
    data = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", output]).stdout)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (320, 240)
    assert float(v["duration"]) == pytest.approx(2, abs=1 / 30)
    assert any(s["codec_type"] == "audio" for s in data["streams"])
    run(["ffmpeg", "-v", "error", "-i", output, "-f", "null", "-"])


def test_hold_resumes_and_overlay_gate(source):
    plan = plan_roasts([FailMoment(0.5, "whiff")], 2, intensity=2)
    def frames(filters):
        raw = run(["ffmpeg", "-v", "error", "-i", source, "-filter_threads", "1", "-vf", filters,
                   "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]).stdout
        size = 320 * 240 * 3
        return [raw[i:i+size] for i in range(0, len(raw), size)]
    actual = frames(video_filter(plan))
    original = frames("null")
    assert len(actual) == len(original) == 60
    assert actual[5] == original[5]
    assert actual[18] == actual[23] == actual[28]
    assert actual[35] != actual[40]
    assert actual[18] != original[18]


def test_multiple_beats_and_end_frame(source):
    plan = plan_roasts([FailMoment(0), FailMoment(0.7), FailMoment(1.99)], 2, intensity=3)
    run(["ffmpeg", "-v", "error", "-i", source, "-filter_threads", "1", "-vf", video_filter(plan),
         "-f", "null", "-"])


def test_existing_sfx_mixer_accepts_specs(source, tmp_path, monkeypatch):
    from pathlib import Path
    from services.ffmpeg_runner import FFmpegRunner
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    plan = plan_roasts([FailMoment(0.5)], 2, intensity=2)
    output = FFmpegRunner(tmp_path, source, 320, 240, 30).overlay_sfx(
        source, plan.to_dict()["sound_effects"], 0)
    assert output != source
    data = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-of", "json", output]).stdout)
    assert float(data["format"]["duration"]) == pytest.approx(2, abs=0.1)
