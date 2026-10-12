import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from social import build_share_kit
from social.metadata import PLATFORM_LIMITS, build_metadata, chapter_text, timeline
from social.thumbnails import SIZES, render_thumbnail, select_frame


@pytest.fixture
def job(tmp_path):
    directory = tmp_path / "job-14"
    directory.mkdir()
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(directory / "final_edit.mp4"),
    ], check=True, capture_output=True)
    return directory


@pytest.fixture
def clips():
    return [{"start": "00:00", "end": "00:02", "description": "Opening play", "score": 2},
            {"start_seconds": 2, "end_seconds": 4, "description": "Last-second save", "score": 9}]


def test_offline_complete_kit(job, clips):
    plan = {"segments": [{"source_start": 0, "source_end": 2}, {"source_start": 2, "source_end": 4}],
            "captions": [{"start": .125, "end": 1.25, "text": "Nice play!"}]}
    kit = build_share_kit(job, clips, plan, "Valorant")
    assert kit == job.parent / "share" / job.name
    assert (kit / "video.mp4").read_bytes() == (job / "final_edit.mp4").read_bytes()
    assert (kit / "chapters.txt").read_text() == "00:00 Opening play\n00:02 Last-second save\n"
    assert "00:00:00,125 --> 00:00:01,250" in (kit / "captions.srt").read_text()
    metadata = json.loads((kit / "metadata.json").read_text())
    assert metadata["provider"] == "template"
    assert metadata["frame_selection"]["clip"] == "Last-second save"
    assert 2 <= metadata["frame_selection"]["timestamp"] < 4
    for variant, size in SIZES.items():
        with Image.open(kit / f"thumbnail_{variant}.jpg") as image:
            assert image.size == size
    with pytest.raises(FileExistsError):
        build_share_kit(job, clips, plan, "Valorant")


@pytest.mark.parametrize("text", ["A" * 160, "One very long dramatic gameplay title " * 8, "", "激しい戦い 🎮 " * 20])
@pytest.mark.parametrize("size", SIZES.values())
def test_text_ink_stays_inside_safe_area(text, size):
    image, layout = render_thumbnail(Image.new("RGB", (640, 360), "navy"), text, size)
    left, top, right, bottom = layout["text_bounds"]
    a, b, c, d = layout["safe_area"]
    assert a <= left < right <= c
    assert b <= top < bottom <= d
    assert image.size == size


def test_reordered_chapters_speeds_effects_and_intro(clips):
    plan = {"segments": [
        {"source_start": 2, "source_end": 4, "speed": .5, "video_effects": ["slow_motion"]},
        {"source_start": 0, "source_end": 2, "speed": 2, "video_effects": ["speed_2x"]},
    ]}
    entries = timeline(clips, plan, 4)
    assert [e["start"] for e in entries] == [4, 12]
    assert entries[-1]["end"] == 12.5
    assert chapter_text(entries, 4) == "00:00 Intro\n00:04 Last-second save\n00:12 Opening play\n"
    assert chapter_text([{"start": 3661, "title": "Late play"}]) == "01:01:01 Late play\n"
    assert chapter_text([{"start": 0, "title": "First"}, {"start": .5, "title": "Second"}]) == "00:00 First\n"


@pytest.mark.parametrize("game,tag", [("Valorant", "#Valorant"), ("Overwatch 2", "#Overwatch2"),
                                      ("Deadlock", "#Deadlock"), ("League", "#LeagueOfLegends")])
def test_limits_and_game_tags(clips, game, tag):
    entries = timeline(clips, {})
    client = Mock(model="mock-model")
    client.client.models.generate_content.return_value.text = json.dumps({"titles": ["Title " * 1000] * 3, "description": "Copy " * 2000})
    data = build_metadata(entries, game, "00:00 A chapter\n" * 1000, client)
    assert data["provider"] == "gemini"
    client.client.models.generate_content.assert_called_once()
    for platform, content in data["platforms"].items():
        assert tag in content["hashtags"]
        assert len(content["description"]) <= PLATFORM_LIMITS[platform]["description"]
        assert all(len(t) <= PLATFORM_LIMITS[platform]["title"] for t in content["titles"])


@pytest.mark.parametrize("response", ["not json", "[]", '{"titles": "wrong", "description": 1}', '{"titles": ["", "a", "b"], "description": "ok"}'])
def test_bad_gemini_metadata_falls_back(clips, response):
    entries = timeline(clips, {})
    client = Mock()
    client.client.models.generate_content.return_value.text = response
    assert build_metadata(entries, "Deadlock", chapter_text(entries), client) == build_metadata(entries, "Deadlock", chapter_text(entries))


@pytest.mark.parametrize("fails", [False, True])
def test_mocked_image_generation_and_failure(job, clips, fails):
    client = Mock(model="mock")
    def generate(reference, prompt, output):
        if fails:
            raise RuntimeError("offline")
        Image.new("RGB", (128, 256), "green").save(output)
        return output
    client.generate_thumbnail.side_effect = generate
    client.client.models.generate_content.side_effect = RuntimeError("offline")
    kit = build_share_kit(job, clips, {"social": {"gemini_image": True, "gemini_metadata": True}}, "Deadlock", client=client)
    client.generate_thumbnail.assert_called_once()
    client.client.models.generate_content.assert_called_once()
    data = json.loads((kit / "metadata.json").read_text())
    assert data["thumbnails"]["youtube"]["provider"] == ("local" if fails else "gemini")
    assert data["provider"] == "template"


def test_client_requires_explicit_flags(job, clips):
    client = Mock()
    build_share_kit(job, clips, {}, "League", client=client)
    assert client.mock_calls == []


def test_optional_sam_and_fallback(monkeypatch):
    frame = Image.new("RGB", (640, 360), "navy")
    cutout = Image.new("RGBA", (200, 200))
    ImageDraw.Draw(cutout).ellipse((20, 20, 180, 180), fill="orange")
    adapter = Mock(return_value=cutout)
    monkeypatch.setitem(sys.modules, "sam", SimpleNamespace(cutout=adapter))
    assert render_thumbnail(frame, "SAVE", SIZES["youtube"], True)[1]["composition"] == "sam"
    adapter.assert_called_once()
    monkeypatch.setitem(sys.modules, "sam", None)
    assert render_thumbnail(frame, "SAVE", SIZES["vertical"], True)[1]["composition"] == "saliency"


def test_frame_ranking_combines_sharpness_and_motion(monkeypatch):
    import io
    frames = [Image.new("RGB", (160, 90), "gray")]
    detailed = frames[0].copy()
    draw = ImageDraw.Draw(detailed)
    for x in range(0, 160, 4):
        draw.line((x, 0, x, 90), fill="white", width=2)
    frames.extend([detailed, Image.new("RGB", (160, 90), "gray")])
    outputs = []
    for frame in frames:
        data = io.BytesIO()
        frame.save(data, format="PNG")
        outputs.append(SimpleNamespace(stdout=data.getvalue()))
    monkeypatch.setattr("social.thumbnails.subprocess.run", Mock(side_effect=outputs))
    _, stats = select_frame("unused.mp4", 0, 3, samples=3)
    assert stats["timestamp"] == 1.5
    assert stats["sharpness"] > 0 and stats["action"] > 0


def test_existing_srt_and_source_timebase(job, clips):
    import shutil
    shutil.copy2(job / "final_edit.mp4", job / "source.mp4")
    srt = "1\n00:00:00,000 --> 00:00:01,000\nHello\n"
    (job / "captions.srt").write_text(srt)
    kit = build_share_kit(job, clips, {}, "League")
    assert (kit / "captions.srt").read_text() == srt
    assert json.loads((kit / "metadata.json").read_text())["frame_selection"]["timebase"] == "source"


def test_failure_does_not_publish_partial_kit(job, clips):
    with pytest.raises(ValueError, match="Captions"):
        build_share_kit(job, clips, {"captions": [{"start": 3, "end": 9, "text": "Oops"}]}, "Valorant")
    assert list((job.parent / "share").iterdir()) == []


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf")])
def test_invalid_speed_rejected(clips, speed):
    with pytest.raises(ValueError):
        timeline(clips, {"segments": [{"source_start": 0, "source_end": 2, "speed": speed}]})


def test_missing_output_and_external_paths(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    with pytest.raises(FileNotFoundError):
        build_share_kit(job, [], {}, "Valorant")
    (tmp_path / "outside.mp4").write_bytes(b"not media")
    with pytest.raises(ValueError, match="inside"):
        build_share_kit(job, [], {"social": {"video_path": "../outside.mp4"}}, "Valorant")


def test_real_montage_intro_offset(job, clips):
    # Four seconds of actual video: 1s intro, a 2s clip accelerated to 1s,
    # then a 2s clip. Source timestamps intentionally differ from output times.
    plan = {"social": {"intro_duration": 1}, "segments": [
        {"source_start": 0, "source_end": 2, "speed": 2},
        {"source_start": 2, "source_end": 4},
    ]}
    kit = build_share_kit(job, clips, plan, "Valorant")
    data = json.loads((kit / "metadata.json").read_text())
    assert [entry["start"] for entry in data["chapters"]] == [0, 1, 2]
    assert (kit / "chapters.txt").read_text().startswith("00:00 Intro\n00:01 Opening play\n")


@pytest.mark.parametrize("option", ["source_path", "captions_path"])
def test_explicit_missing_files_are_errors(job, clips, option):
    with pytest.raises(ValueError, match="inside"):
        build_share_kit(job, clips, {"social": {option: "missing.file"}}, "Valorant")
    assert not (job.parent / "share" / job.name).exists()


def test_text_wrap_preserves_words():
    _, layout = render_thumbnail(Image.new("RGB", (640, 360)), "LAST SECOND SAVE", SIZES["youtube"])
    assert " ".join(layout["text"].split()) == "LAST SECOND SAVE"


def test_provider_error_logs_do_not_expose_exception_text(clips, caplog):
    client = Mock()
    client.client.models.generate_content.side_effect = RuntimeError("private-provider-detail")
    entries = timeline(clips, {})
    assert build_metadata(entries, "Valorant", "", client)["provider"] == "template"
    assert "using template copy" in caplog.text
    assert "private-provider-detail" not in caplog.text


def test_timeline_overlap_ties_keep_first_description():
    clips = [{"start": 0, "end": 2, "description": "First"},
             {"start": 2, "end": 4, "description": "Second"}]
    entries = timeline(clips, {"segments": [{"start": 1, "end": 3}, {"start": 5, "end": 6}]})
    assert [entry["title"] for entry in entries] == ["First", "Play 2"]
