"""Local-only tests; all media is synthesized with FFmpeg in temporary dirs."""

import json
import shutil
import subprocess
import sys

import numpy as np
import pytest

from signals import Config, detect_candidates
from signals.detector import _audio, _probe, _video
from signals.fusion import fuse, zscore
from signals.models import WEIGHTS
from signals.ocr import HUDReader, classify, regions_for


def make_video(path, video, audio=None, duration=12):
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        command += ["-f", "lavfi", "-i", audio]
    command += ["-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast",
                "-threads", "2", "-pix_fmt", "yuv420p"]
    if audio:
        command += ["-c:a", "aac"]
    subprocess.run(command + [str(path)], check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def burst(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("signals") / "burst.mp4",
                      "testsrc2=s=640x360:r=24,drawbox=color=black:t=fill:enable='not(between(t,4,7))'",
                      "sine=frequency=440:sample_rate=16000,volume='if(between(t,4,7),5,0.01)':eval=frame")


def test_synthetic_burst_is_ranked_and_trimmed(burst):
    candidates = detect_candidates(burst, scene_backend="ffmpeg")
    assert candidates
    first = candidates[0]
    assert first.start <= 4.5 and first.end >= 7
    assert first.start >= 2 and first.end <= 9
    assert first.signals["motion"] > 0
    assert first.signals["rms"] > 0
    assert any(e["type"] == "sustained_audio" for e in first.events)
    assert candidates == detect_candidates(burst, scene_backend="ffmpeg")
    assert json.loads(json.dumps(first.to_dict()))["start"] == first.start


def test_audio_onset_and_sustained(burst):
    rms, onset, sustained, events = _audio(burst, 12, True, Config())
    assert rms[5] > 50 * rms[1]
    assert 3 <= np.argmax(onset) <= 4
    assert sustained[5] > .8
    assert 3.8 <= events[0]["time"] <= 4.2


def test_silent_static_and_missing_audio(tmp_path):
    path = make_video(tmp_path / "static.mp4", "color=c=black:s=320x180:r=12", duration=3)
    assert detect_candidates(path) == []
    zeros = _audio(path, 3, False, Config())
    assert all(not np.any(x) for x in zeros[:3])


def test_scene_cut(tmp_path):
    path = make_video(tmp_path / "cut.mp4",
                      "color=c=black:s=320x180:r=12,drawbox=color=white:t=fill:enable='gte(t,5)'",
                      duration=10)
    duration, stream, _ = _probe(path)
    _, scene, events = _video(path, duration, stream, Config(scene_backend="ffmpeg"), {})
    assert scene[5] == 1
    assert events == [{"time": 5., "type": "scene_cut"}]


def test_optional_ocr_missing(monkeypatch, burst):
    original = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "tesseract" else original(name))
    with pytest.warns(RuntimeWarning, match="Tesseract"):
        actual = detect_candidates(burst, ocr=True, scene_backend="ffmpeg")
    assert actual == detect_candidates(burst, scene_backend="ffmpeg")


def test_optional_scene_missing(monkeypatch, burst):
    monkeypatch.setitem(sys.modules, "scenedetect", None)
    monkeypatch.delitem(sys.modules, "scenedetect.detectors", raising=False)
    with pytest.warns(RuntimeWarning, match="PySceneDetect"):
        actual = detect_candidates(burst, scene_backend="content")
    assert actual == detect_candidates(burst, scene_backend="ffmpeg")


@pytest.mark.skipif(not shutil.which("tesseract"), reason="optional Tesseract binary")
def test_real_drawtext_ocr(tmp_path):
    path = make_video(tmp_path / "banner.mp4",
                      "color=c=black:s=960x540:r=12,"
                      "drawtext=text='ELIMINATED BY':fontcolor=white:fontsize=44:"
                      "x=(w-tw)/2:y=h/2:enable='between(t,4,6)'", duration=10)
    candidates = detect_candidates(path, ocr=True, profile="overwatch2", scene_backend="ffmpeg")
    assert candidates
    deaths = [e for c in candidates for e in c.events if e["type"] == "death"]
    assert len(deaths) == 1
    assert 4 <= deaths[0]["time"] <= 4.5
    assert "ELIMINATED BY" in deaths[0]["text"]


def raw_signals(length):
    return {key: np.zeros(length) for key in WEIGHTS}


def test_fusion_merge_bounds_ranking_and_constant_signals():
    raw = raw_signals(60)
    raw["motion"][10:13] = .2
    raw["motion"][16:18] = .3
    raw["ocr"][45] = 1
    events = [{"time": 45., "type": "kill"}]
    candidates = fuse(raw, events, 60, Config(trim_dead_air=False))
    assert candidates[0].events == events
    assert any(c.start <= 10 and c.end >= 18 for c in candidates)
    for c in candidates:
        assert 0 <= c.start < c.end <= 60
        assert 3 <= c.end - c.start <= 20
        assert np.isfinite(c.score)
    assert np.all(zscore(np.ones(5)) == 0)


def test_long_action_is_split_without_overlap():
    raw = raw_signals(80)
    raw["motion"][10:60:2] = 1
    result = fuse(raw, [], 80, Config(max_length=12, trim_dead_air=False, peak_threshold=.1))
    assert len(result) >= 3
    ordered = sorted(result, key=lambda c: c.start)
    assert all(3 <= c.end - c.start <= 12.001 for c in result)
    assert all(a.end <= b.start for a, b in zip(ordered, ordered[1:]))
    assert ordered[-1].end >= 58


def test_short_clip_and_edge_peaks():
    raw = raw_signals(2)
    raw["ocr"][0] = 1
    result = fuse(raw, [{"time": 0., "type": "kill"}], 1.5, Config())
    assert len(result) == 1
    assert result[0].start == 0 and result[0].end == 1.5


@pytest.mark.parametrize("cfg", [{"sample_fps": 0}, {"weights": {"bad": 2}},
                                    {"weights": {"rms": float("nan")}}, {"width": 20.5},
                                    {"min_length": 20, "max_length": 5}, {"pre_roll": -1}])
def test_invalid_config(cfg):
    with pytest.raises(ValueError):
        Config(**cfg)


def test_profiles_and_classification():
    assert regions_for("Overwatch 2", None) == regions_for("overwatch2", None)
    assert classify("ELIMINATED BY player")[0] == "death"
    assert classify("ELIMINATED player")[0] == "kill"
    assert classify("skill rating")[0] is None
    with pytest.raises(ValueError):
        regions_for("unknown", None)
    with pytest.raises(ValueError):
        regions_for("auto", {"bad": (0, 0, 2, 1)})


def test_cli_json_and_error(burst):
    result = subprocess.run([sys.executable, "-m", "signals", str(burst)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["score"] > 0
    result = subprocess.run([sys.executable, "-m", "signals", "missing.mp4"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert not result.stdout


def test_corrupt_input(tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"not a video")
    with pytest.raises(subprocess.CalledProcessError):
        detect_candidates(path)
