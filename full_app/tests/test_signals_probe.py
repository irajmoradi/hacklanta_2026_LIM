"""The analysis modules intentionally use different stream/duration policies."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from audio_ai.analyzer import _decode
from profiles import detect_game
from signals.detector import _probe
from social import _duration
from vjepa.features import video_duration
from vjepa.media import probe_media


def test_duration_policies_preserve_container_and_stream_clocks(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"
    path.touch()
    stream = {"codec_type": "video", "duration": "2", "index": 0}
    data = {"streams": [stream], "format": {"duration": "3"}}
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=json.dumps(data)))
    assert _probe(path) == (2, stream, False)
    assert video_duration(path) == 2
    assert _duration(path) == 3
    samples, duration, has_audio = _decode(path, 0)
    assert samples.size == 0 and duration == 3 and not has_audio
    del stream["duration"]
    assert _probe(path)[0] == video_duration(path) == 3


def test_candidate_probe_ignores_cover_art(monkeypatch):
    artwork = {"codec_type": "video", "duration": "99", "disposition": {"attached_pic": 1}}
    video = {"codec_type": "video", "duration": "2"}
    data = {"streams": [artwork, {"codec_type": "audio"}, video], "format": {"duration": "3"}}
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=json.dumps(data)))
    assert _probe("video.mp4") == (2, video, True)
    data["streams"].remove(video)
    with pytest.raises(ValueError, match="no video stream"):
        _probe("audio.mp3")


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("ffprobe", 20),
                                  subprocess.CalledProcessError(1, "ffprobe"),
                                  FileNotFoundError("ffprobe")])
def test_probe_errors_propagate_but_game_detection_falls_back(tmp_path, monkeypatch, error):
    path = tmp_path / "video.mp4"
    path.touch()
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr("profiles.detection.shutil.which", lambda name: name)
    with pytest.raises(type(error)):
        probe_media(path, timeout=20)
    assert detect_game(path) == ("generic", 0.0)
