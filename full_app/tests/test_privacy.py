import json
import subprocess

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from privacy import (BlurBox, BlurTrack, PrivacyOptions, build_filtergraph,
                     detect_video, render_private_source, render_montage, sanitize)
from privacy.detector import smooth
from privacy.ocr import RapidOCR, Tesseract, Word
from privacy.profiles import regions_for


FULL = {"chat": {"x": 0, "y": 0, "width": 1, "height": 1}}


@pytest.fixture
def names_video(tmp_path):
    path = tmp_path / "names.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=640x240:r=10:d=2,"
        "drawtext=text='Uploader':x=30:y=40:fontsize=32:fontcolor=white,"
        "drawtext=text='EnemyPlayer':x=300:y=40:fontsize=32:fontcolor=white,"
        "drawtext=text='Secret chat message':x=30:y=160:fontsize=28:fontcolor=white",
        "-c:v", "ffv1", str(path),
    ], check=True, capture_output=True, timeout=30)
    return path


class FakeReader:
    def __init__(self):
        self.calls = 0

    def read(self, frame):
        self.calls += 1
        assert frame.shape == (240, 640, 3)
        if self.calls == 2:  # A dropped OCR sample should not cause flicker.
            return []
        return [Word("Uploader", 30, 40, 150, 32), Word("EnemyPlayer", 300, 40, 210, 32)]


def test_detection_hold_whitelist_and_no_text_in_track(names_video):
    reader = FakeReader()
    track = detect_video(names_video, {"regions": FULL, "keep_own_name": True,
                                     "own_name": " UPLOADER "}, reader=reader)
    assert reader.calls == 4
    assert len(track.boxes) == 1
    assert track.boxes[0].start == 0 and track.boxes[0].end == 2
    assert track.boxes[0].x > .4
    assert "EnemyPlayer" not in track.model_dump_json()
    hidden = detect_video(names_video, {"regions": FULL}, reader=FakeReader())
    assert len(hidden.boxes) == 2


def test_real_tesseract_drawn_names_and_chat(names_video):
    # Required Linux runner includes Tesseract: do not silently skip acceptance.
    track = detect_video(names_video, {"regions": FULL, "keep_own_name": True,
                                     "own_name": "Uploader"}, reader=Tesseract())
    assert any(b.x > .4 and b.y < .4 for b in track.boxes)
    assert any(b.y > .5 for b in track.boxes)
    assert not any(b.x < .25 and b.y < .4 for b in track.boxes)


@pytest.mark.parametrize("game", ["valorant", "OW2", "deadlock", "League of Legends"])
def test_profiles(game):
    assert {"chat", "kill_feed", "scoreboard", "nameplates", "party_voice", "notifications", "webcam"} <= regions_for(PrivacyOptions(game=game)).keys()


def test_optional_ocr_fallback_webcam_and_manual(names_video, monkeypatch):
    def unavailable(_):
        raise ImportError("optional backend missing")
    monkeypatch.setattr("privacy.detector.get_reader", unavailable)
    payload = {"regions": {**FULL, "webcam": {"x": 0, "y": 0, "width": .1, "height": .1}},
               "blur_webcam": True, "manual_boxes": [dict(x=.7, y=.7, width=.1, height=.1, start=.5, end=1)]}
    track = detect_video(names_video, payload)
    assert {b.kind for b in track.boxes} == {"chat", "webcam", "manual"}
    assert track.warnings
    assert BlurTrack.model_validate_json(track.model_dump_json()) == track
    payload["blur_webcam"] = False
    assert "webcam" not in {b.kind for b in detect_video(names_video, payload).boxes}


def test_failed_reader_covers_full_duration(names_video):
    class Broken:
        def read(self, frame):
            raise RuntimeError("engine failed")
    track = detect_video(names_video, {"regions": FULL}, reader=Broken())
    assert track.warnings and track.boxes[0].start == 0 and track.boxes[0].end == 2


@pytest.mark.parametrize("bad", [dict(x=-1), dict(width=0), dict(end=0), dict(start=2),
                                  dict(x=.9, width=.2), dict(x=float("nan")), dict(end=float("inf"))])
def test_invalid_boxes(bad):
    with pytest.raises(ValidationError):
        BlurBox.model_validate(dict(x=.1, y=.1, width=.2, height=.2, end=2) | bad)


def test_invalid_inputs(names_video):
    with pytest.raises(ValueError, match="unknown"):
        detect_video(names_video, {"game": "unknown"})
    with pytest.raises(ValueError, match="metadata"):
        detect_video("missing-video.mp4")
    with pytest.raises(ValueError, match="duration"):
        detect_video(names_video, {"manual_boxes": [dict(x=0, y=0, width=1, height=1, end=999)]})
    with pytest.raises(ValueError, match="webcam"):
        detect_video(names_video, {"regions": {}, "blur_webcam": True})


def test_temporal_union():
    boxes = [BlurBox(x=.1, y=.1, width=.1, height=.1, start=0, end=1),
             BlurBox(x=.15, y=.1, width=.1, height=.1, start=.8, end=2),
             BlurBox(x=.15, y=.1, width=.1, height=.1, start=3, end=4)]
    result = smooth(boxes)
    assert len(result) == 2
    assert result[0].width == pytest.approx(.15)
    assert result[0].end == 2


def frame_at(path, index):
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        assert ok
        return frame
    finally:
        cap.release()


def test_filter_pixels_and_time_boundaries(names_video, tmp_path):
    track = BlurTrack(width=640, height=240, duration=2, boxes=[
        BlurBox(x=290/640, y=30/240, width=240/640, height=55/240, start=.5, end=1.5)])
    # Lossless output isolates filter changes from codec changes.
    path = tmp_path / "filtered.mkv"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(names_video),
                    "-filter_complex_threads", "1", "-filter_complex", build_filtergraph(track),
                    "-map", "[privacy]", "-c:v", "ffv1", str(path)], check=True, capture_output=True)
    original = frame_at(names_video, 0)
    for index in [0, 4, 15, 19]:
        assert np.max(cv2.absdiff(frame_at(path, index), original)) <= 2
    for index in [5, 10, 14]:
        delta = cv2.absdiff(frame_at(path, index), original)
        assert delta[30:85, 290:530].mean() > 10
        delta[30:85, 290:530] = 0
        assert delta.max() <= 2  # Includes uploader and chat: exact spatial isolation.


def test_render_api_audio_and_validation(video, tmp_path):
    output, track = sanitize(video, tmp_path / "private.mp4", {
        "backend": "none", "regions": {}, "manual_boxes": [
            dict(x=0, y=0, width=.2, height=.2, start=1, end=2)]})
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
                           check=True, capture_output=True, text=True)
    assert {s["codec_type"] for s in json.loads(probe.stdout)["streams"]} == {"video", "audio"}
    with pytest.raises(ValueError, match="differ"):
        render_private_source(video, video, track)
    track.width = 999
    with pytest.raises(ValueError, match="dimensions"):
        render_private_source(video, tmp_path / "wrong.mp4", track)


def test_rapidocr_adapter_without_optional_dependency():
    reader = RapidOCR.__new__(RapidOCR)
    reader.engine = lambda frame: ([[[[10, 20], [40, 20], [40, 30], [10, 30]], "Other", .9]], None)
    assert reader.read(np.zeros((50, 50, 3), dtype=np.uint8)) == [Word("Other", 10, 20, 31, 11)]


def test_whitelist_does_not_allow_substrings_or_mixed_lines(names_video):
    class Reader:
        def read(self, frame):
            return [Word("Uploader Enemy", 10, 10, 150, 30),
                    Word("Uploader2", 300, 100, 100, 30)]
    track = detect_video(names_video, {"regions": FULL, "own_name": "Uploader", "keep_own_name": True}, reader=Reader())
    assert len(track.boxes) == 2


def test_montage_adapter_preserves_runner_and_cleans_source(video, tmp_path, monkeypatch):
    from services.ffmpeg_runner import FFmpegRunner
    monkeypatch.setattr("services.ffmpeg_runner.HAS_NVENC", False)
    runner = FFmpegRunner(tmp_path, video, 160, 120, 10)
    final, track = render_montage(runner, {"segments": [
        {"source_start": 1, "source_end": 2, "video_effects": [], "speed": 1.5}
    ]}, {"backend": "none", "regions": {}, "manual_boxes": [
        dict(x=0, y=0, width=.2, height=.2, start=1, end=2)]})
    assert final.exists()
    assert runner.source == video and video.exists()
    assert not list(tmp_path.glob("privacy-*"))
    assert track.boxes[0].start == 1
    assert frame_at(final, 0).shape == (120, 160, 3)
