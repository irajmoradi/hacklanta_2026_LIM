"""Offline renderer tests: all media is synthesized locally by FFmpeg."""

import builtins
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from render import RenderPlan
from render.analysis import detect_beats, motion_track, smooth_track, snap_durations
from render.captions import transcribe, write_ass
from render.engine import probe
from render.graph import join_graph, music_graph, reframe_graph
from render.plan import Captions, TrackPoint, Word
from services.ffmpeg_runner import FFmpegRunner


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True,
                   capture_output=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    source = root / "source.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=20:d=3",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
           "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", source)
    silent = root / "silent.mp4"
    ffmpeg("-i", source, "-an", "-c:v", "copy", silent)
    music = root / "music.wav"
    ffmpeg("-f", "lavfi", "-i",
           "aevalsrc=if(lt(mod(t\\,0.5)\\,0.05)\\,0.8*sin(2*PI*180*t)\\,0):s=8000:d=3", music)
    return source, silent, music


@pytest.fixture(autouse=True)
def cpu(monkeypatch):
    monkeypatch.setattr("services.ffmpeg_runner.HAS_NVENC", False)


def run_plan(source, tmp_path, **kwargs):
    payload = dict(segments=[dict(source_start=0.2, source_end=0.8)], resolution=720, fps=20)
    payload.update(kwargs)
    plan = RenderPlan(**payload)
    runner = FFmpegRunner(tmp_path, source, 320, 180, 20)
    output = runner.render(plan.model_dump())
    return plan, probe(output), output


def assert_media(info, size, duration):
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == size
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert video["sample_aspect_ratio"] == "1:1"
    assert audio["codec_name"] == "aac"
    assert audio["sample_rate"] == "48000"
    assert audio["channels"] == 2
    assert abs(float(info["format"]["duration"]) - duration) < 0.11
    assert abs(float(video["duration"]) - float(audio["duration"])) < 0.11


@pytest.mark.parametrize("preset", ["landscape", "vertical", "square"])
@pytest.mark.parametrize("resolution", [720, 1080])
def test_presets(media, tmp_path, preset, resolution):
    plan, info, _ = run_plan(media[0], tmp_path, preset=preset, resolution=resolution)
    assert_media(info, plan.size, 0.6)


@pytest.mark.parametrize("transition", ["cut", "fast_zoom", "whip", "flash", "glitch"])
def test_transitions(media, tmp_path, transition):
    segments = [dict(source_start=i * 0.7, source_end=i * 0.7 + 0.6) for i in range(3)]
    plan, info, _ = run_plan(media[0], tmp_path, segments=segments, transition=transition,
                            transition_duration=0.15)
    assert_media(info, plan.size, 1.8 if transition == "cut" else 1.5)


@pytest.mark.parametrize("mode", ["motion", "blur", "crosshair"])
def test_silent_reframe(media, tmp_path, mode):
    plan, info, _ = run_plan(media[1], tmp_path, reframe=mode, preset="vertical")
    assert_media(info, plan.size, 0.6)


def test_full_features(media, tmp_path, monkeypatch):
    from models.effects import SOUND_EFFECTS
    monkeypatch.setitem(SOUND_EFFECTS, "synthetic", {"file": str(media[2])})
    segments = [dict(source_start=0.1, source_end=1.1, title="Let's {win}: 100% \\ go",
                     video_effects=["text_gg", "saturation_boost"],
                     sound_effects=[dict(sfx_key="synthetic", offset_in_segment=0.1)],
                     words=[dict(start=0.1, end=0.4, text="shit!")],
                     sam={"subject_track": [dict(time=0, x=0.1), dict(time=0.9, x=0.9)]}),
                dict(source_start=1.2, source_end=2.2)]
    plan, info, _ = run_plan(media[0], tmp_path, segments=segments, preset="vertical",
                            captions=dict(enabled=True, mask_profanity=True),
                            intro=dict(text="Intro", duration=0.4), outro=dict(text="Done", duration=0.4),
                            music=dict(path=str(media[2]), beat_sync=True, beats=[0.5, 1.25, 2.0]),
                            transition="flash", transition_duration=0.1)
    # intro .4 + trimmed .95 + 1 + outro .4 - three overlaps .1
    assert_media(info, plan.size, 2.45)


def test_graph_snapshots():
    snapshots = Path(__file__).parent / "snapshots"
    cases = {"reframe": reframe_graph((720, 1280)),
             "blur": reframe_graph((720, 1280), "blur"),
             "join": join_graph([1, 1, 1], "flash", 0.1, 30),
             "music": music_graph(0.18, True)}
    for name, graph in cases.items():
        assert graph + "\n" == (snapshots / f"{name}.txt").read_text()


def test_schema_and_bounds():
    for data in [dict(segments=[]), dict(segments=[dict(source_start=2, source_end=1)]),
                 dict(segments=[dict(source_start=0, source_end=float("inf"))]),
                 dict(segments=[dict(source_start=0, source_end=1, video_effects=["speed_2x"])]),
                 dict(segments=[dict(source_start=0, source_end=1, sam={"subject_track": [
                     dict(time=0, x=0.2), dict(time=0, x=0.8)]})])]:
        with pytest.raises(ValidationError):
            RenderPlan(**data)
    assert "segments" in RenderPlan.model_json_schema()["properties"]


def test_analysis(media):
    track = motion_track(media[0], 0, 1)
    assert len(track) == 4
    assert all(0 <= p.x <= 1 and 0 <= p.y <= 1 for p in track)
    smoothed = smooth_track([TrackPoint(time=0, x=1), TrackPoint(time=1, x=0)])
    assert smoothed[0].x == pytest.approx(0.65)
    assert abs(smoothed[1].x - smoothed[0].x) < 0.3
    beats = detect_beats(media[2], 2.5)
    assert any(abs(b - 0.5) < 0.1 for b in beats)
    assert snap_durations([1, 1, 1], [0.8, 1.7], 0.25, 0.1) == pytest.approx([0.9, 1, 1])
    assert snap_durations([1, 1], [1.1], 0.25) == [1, 1]  # never extend


def test_caption_text_and_optional_dependency(tmp_path, monkeypatch):
    ass = tmp_path / "caption.ass"
    write_ass(ass, [Word(start=0, end=0.4, text=r"SHIT! {\pos(0,0)}")],
              (720, 1280), "vertical", Captions(mask_profanity=True), 0.3)
    text = ass.read_text()
    assert "****!" in text and "SHIT" not in text
    assert r"{\pos" not in text
    assert "0:00:00.30" in text
    assert ",256,1" in text
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("optional")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.warns(RuntimeWarning, match="unavailable"):
        assert transcribe("unused", "tiny") == []


def test_legacy_dispatch(tmp_path, monkeypatch):
    runner = FFmpegRunner(tmp_path, tmp_path / "unused.mp4", 320, 180, 20)
    monkeypatch.setattr(runner, "_render_one_segment", lambda i, s: (i, Path("legacy.mp4")))
    monkeypatch.setattr(runner, "concatenate", lambda paths: paths[0])
    assert runner.render({"segments": [{}]}) == Path("legacy.mp4")


def test_out_of_range_preserves_output(media, tmp_path):
    final = tmp_path / "final_edit.mp4"
    final.write_bytes(b"previous output")
    with pytest.raises(ValueError, match="past source"):
        run_plan(media[0], tmp_path, segments=[dict(source_start=0, source_end=100)])
    assert final.read_bytes() == b"previous output"


def test_long_card_text(tmp_path):
    path = tmp_path / "card.ass"
    write_ass(path, [], (720, 720), "square", Captions(), 5, "Still here", title_duration=5)
    assert "0:00:05.00,Title" in path.read_text()


def test_dense_track_and_auto_beats(media, tmp_path):
    points = [dict(time=i / 500, x=0.2 + i / 1000) for i in range(500)]
    plan, info, _ = run_plan(media[0], tmp_path, preset="vertical",
                            segments=[dict(source_start=0, source_end=1,
                                           sam={"subject_track": points}),
                                      dict(source_start=1, source_end=2)],
                            music=dict(path=str(media[2]), beat_sync=True, duck=False))
    assert_media(info, plan.size, 2)


def test_nvenc_retry(tmp_path, monkeypatch):
    from render.engine import Renderer
    monkeypatch.setattr("services.ffmpeg_runner.HAS_NVENC", True)
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if "h264_nvenc" in command else 0,
                                           stderr="No GPU")
    monkeypatch.setattr("render.engine.subprocess.run", execute)
    renderer = Renderer(FFmpegRunner(tmp_path, tmp_path / "source", 320, 180, 20))
    renderer.encode([], tmp_path / "out.mp4", tmp_path)
    assert len(calls) == 2
    assert "h264_nvenc" in calls[0] and "libx264" in calls[1]


def test_transcription_adapter(monkeypatch):
    import sys
    from types import SimpleNamespace
    seen = {}
    class FakeWhisper:
        def __init__(self, name, **kwargs):
            seen.update(kwargs)
        def transcribe(self, path, **kwargs):
            seen.update(kwargs)
            return iter([SimpleNamespace(words=[SimpleNamespace(start=0.1, end=0.4, word=" Nice ")])]), None
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisper))
    assert transcribe("unused.wav", "tiny") == [Word(start=0.1, end=0.4, text="Nice")]
    assert seen["local_files_only"] and seen["word_timestamps"] and seen["vad_filter"]


def test_ducking_reduces_music(tmp_path):
    from array import array
    import math
    import sys
    # Key is a 2 kHz voice stand-in active in the middle second. Bed is 100 Hz.
    voice = "aevalsrc=if(between(t\\,1\\,2)\\,0.6*sin(2*PI*2000*t)\\,0):s=48000:d=3"
    bed = "sine=frequency=100:sample_rate=48000:duration=3"
    levels = []
    for duck in (False, True):
        graph = music_graph(0.5, duck).replace("[outa]", "[mixed]")
        graph += ";[mixed]lowpass=f=200:p=2,lowpass=f=200:p=2[outa]"
        result = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", voice,
                                 "-f", "lavfi", "-i", bed, "-filter_complex", graph,
                                 "-map", "[outa]", "-ac", "1", "-f", "f32le", "-"],
                                capture_output=True, check=True)
        samples = array("f", result.stdout)
        if sys.byteorder != "little":
            samples.byteswap()
        middle = samples[int(1.4 * 48000):int(1.8 * 48000)]
        levels.append(math.sqrt(sum(s * s for s in middle) / len(middle)))
    assert levels[1] < levels[0] * 0.6
