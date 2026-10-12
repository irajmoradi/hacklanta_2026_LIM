"""EXT-18: real FFmpeg renders from synthetic media; no network or Gemini."""

import json
import subprocess

import pytest

from fx import REGISTRY, Request, Timing, compose, metadata
from fx.preview import probe, run


@pytest.fixture(scope="module")
def fx_source(tmp_path_factory):
    source = tmp_path_factory.mktemp("fx") / "source.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=2",
         "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", source])
    return source


def assert_video(path, duration):
    stream = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (160, 120)
    assert stream["pix_fmt"] == "yuv420p"
    assert float(stream["duration"]) == pytest.approx(duration, abs=2 / 30)
    run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"])


@pytest.mark.parametrize("name", REGISTRY)
def test_every_effect_renders(name, fx_source, tmp_path):
    effect = REGISTRY[name]
    timing = Timing(2, 0.5, 1)
    path = effect.preview(fx_source, tmp_path / "preview.mp4", timing)
    assert_video(path, 1.75 if name == "speed_ramp" else 2)


@pytest.mark.parametrize("params,expected", [
    ({"fast": 2.0, "slow": 0.25}, 2.75),
    ({"fast": 1.0, "slow": 1.0}, 2.0),
    ({"interpolation": "minterpolate"}, 1.75),
])
def test_speed_duration(params, expected, fx_source, tmp_path):
    effect = REGISTRY["speed_ramp"]
    timing = Timing(2, 0.5, 1)
    assert effect.output_duration(timing, **params) == expected
    assert_video(effect.preview(fx_source, tmp_path / "ramp.mp4", timing, **params), expected)


@pytest.mark.parametrize("preset", ["high-contrast", "neon"])
def test_grades(preset, fx_source, tmp_path):
    assert_video(REGISTRY["color_grade"].preview(fx_source, tmp_path / "grade.mp4", Timing(2), preset=preset), 2)


def test_composition(fx_source, tmp_path):
    requests = [Request("speed_ramp", Timing(2)), Request("zoom_punch", Timing(1.75)),
                Request("rgb_split", Timing(1.75)), Request("letterbox", Timing(1.75)),
                Request("kill_counter", Timing(1.75), {"count": 4})]
    output = tmp_path / "composed.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", fx_source, "-filter_threads", "1", "-vf",
         compose(requests) + ",format=yuv420p", "-c:v", "libx264", "-threads", "2", output])
    assert_video(output, 1.75)
    with pytest.raises(ValueError, match="preceding"):
        compose([requests[0], Request("letterbox", Timing(2))])


def test_freeze_holds_hit_and_resumes(fx_source):
    # Lossless raw frames avoid codec noise; compare held frames and resumed motion.
    chain = REGISTRY["freeze_name_tag"].filter(Timing(2), name="ACE")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(fx_source), "-filter_threads", "1",
                          "-vf", chain, "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         check=True, capture_output=True, timeout=30).stdout
    size = 160 * 120 * 3
    frame = lambda n: raw[n * size:(n + 1) * size]
    assert frame(17) == frame(23) == frame(28)
    assert frame(33) != frame(38)


@pytest.mark.parametrize("name,params", [
    ("speed_ramp", {"slow": 0}), ("screen_shake", {"pixels": 1.5}),
    ("color_grade", {"preset": "unknown"}), ("freeze_name_tag", {"name": "x';movie=/etc/passwd"}),
    ("letterbox", {"fraction": float("nan")}), ("impact_frame", {"unknown": 1}),
])
def test_bad_params(name, params):
    with pytest.raises(ValueError):
        REGISTRY[name].filter(Timing(2), **params)


@pytest.mark.parametrize("values", [(0, 0, 1), (2, -1, 1), (2, 1, 1), (2, 0, 3), (float("inf"), 0, 1)])
def test_bad_timing(values):
    with pytest.raises(ValueError):
        Timing(*values)


def test_metadata_is_json_and_builders_are_pure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("Pure builder performed IO"))
    assert len(json.loads(json.dumps(metadata()))) == 12
    for effect in REGISTRY.values():
        assert effect.filter(Timing(2)) == effect.filter(Timing(2))


def test_optional_rife_fallback(fx_source, tmp_path):
    def missing(*args):
        raise ImportError("RIFE not installed")
    with pytest.warns(RuntimeWarning, match="retaining FFmpeg"):
        path = REGISTRY["speed_ramp"].preview(fx_source, tmp_path / "fallback.mp4", Timing(2), rife_hook=missing)
    assert_video(path, 1.75)


def test_optional_rife_hook(fx_source, tmp_path):
    import shutil
    calls = []
    def hook(source, target, fps):
        calls.append(fps)
        shutil.copyfile(source, target)
    path = REGISTRY["speed_ramp"].preview(fx_source, tmp_path / "hook.mp4", Timing(2), rife_hook=hook)
    assert calls == [30]
    assert_video(path, 1.75)


def test_invalid_rife_output_keeps_preview(fx_source, tmp_path):
    def hook(source, target, fps):
        run(["ffmpeg", "-v", "error", "-y", "-i", source, "-vf", "scale=80:60",
             "-threads", "1", target])
    with pytest.warns(RuntimeWarning, match="changed geometry"):
        path = REGISTRY["speed_ramp"].preview(fx_source, tmp_path / "invalid.mp4", Timing(2), rife_hook=hook)
    assert_video(path, 1.75)


@pytest.mark.parametrize("name", ["impact_frame", "freeze_name_tag", "speed_ramp"])
@pytest.mark.parametrize("window", [(0, 2), (1.5, 2), (0, 0.5)])
def test_timeline_boundaries(name, window, fx_source, tmp_path):
    timing = Timing(2, *window)
    effect = REGISTRY[name]
    expected = (2 - window[1] + window[0]) / 2 + (window[1] - window[0]) * 2 if name == "speed_ramp" else 2
    assert_video(effect.preview(fx_source, tmp_path / "edge.mp4", timing), expected)


def test_contact_sheet(tmp_path):
    from fx.contact_sheet import generate
    path = generate(tmp_path)
    stream = probe(path)["streams"][0]
    assert (stream["width"], stream["height"]) == (1280, 630)
    assert len(list(tmp_path.glob("*.mp4"))) == 13
