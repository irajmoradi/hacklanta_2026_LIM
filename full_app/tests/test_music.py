"""Offline music tests using synthesized audio only (no network or paid APIs)."""

import builtins
import json
import subprocess
import wave

import numpy as np
import pytest

from music import analyze_track, load_manifest, pick_or_generate
from music.analysis import analyze_samples
from music.audio import SAMPLE_RATE, read_audio, write_audio
from music.library import select_track


def pcm(path):
    with wave.open(str(path), "rb") as source:
        assert source.getnchannels() == 1
        assert source.getsampwidth() == 2
        assert source.getframerate() == SAMPLE_RATE
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2") / 32768


@pytest.mark.parametrize("style,bpm", [("energetic", 120), ("energetic", 140), ("chill", 85), ("chill", 100)])
def test_generated_length_tempo_and_sections(tmp_path, style, bpm):
    bed = pick_or_generate(style, 19.123, 5.137, bpm=bpm, output_dir=tmp_path)
    samples = pcm(bed.path)
    assert abs(len(samples) / SAMPLE_RATE - 19.123) <= 1 / SAMPLE_RATE
    assert bed.bpm == bpm
    assert bed.source == "procedural"
    assert bed.license is None  # no invented third-party license
    assert bed.beats == sorted(bed.beats)
    assert all(0 <= b < 19.123 for b in bed.beats)
    assert min(abs(b - 5.137) for b in bed.beats) < 1e-9
    assert np.diff(bed.beats) == pytest.approx(60 / bpm)
    assert [s.name for s in bed.sections] == ["intro", "drop", "outro"]
    assert bed.sections[0].start == 0
    assert bed.sections[0].end == bed.sections[1].start == 5.137
    assert bed.sections[1].end == bed.sections[2].start
    assert bed.sections[2].end == 19.123
    assert abs(samples).max() <= .901
    assert abs(samples[0]) < .0001 and abs(samples[-1]) < .0001
    # Estimate tempo from the rendered waveform, independently of metadata.
    report = analyze_track(bed.path, use_librosa=False)
    assert report.bpm == pytest.approx(bpm, abs=3)
    assert report.energy > .01
    # Audible dynamic lift, not just a label marking the climax.
    before = samples[round(3 * SAMPLE_RATE):round(5 * SAMPLE_RATE)]
    after = samples[round(5.137 * SAMPLE_RATE):round(7.137 * SAMPLE_RATE)]
    assert np.sqrt(np.mean(after ** 2)) > 1.4 * np.sqrt(np.mean(before ** 2))


def test_deterministic_unique_outputs_and_style(tmp_path):
    a = pick_or_generate("energetic", 4, 1, output_dir=tmp_path)
    b = pick_or_generate("energetic", 4, 1, output_dir=tmp_path)
    c = pick_or_generate("chill", 4, 1, output_dir=tmp_path)
    d = pick_or_generate("energetic", 4, 1, output_dir=tmp_path, seed=2)
    assert a.path != b.path
    assert a.path.read_bytes() == b.path.read_bytes()
    assert a.path.read_bytes() != c.path.read_bytes()
    assert a.path.read_bytes() != d.path.read_bytes()
    assert a.bpm == 140 and c.bpm == 85


@pytest.mark.parametrize("length,climax", [(1 / SAMPLE_RATE, 0), (.1, .05), (2, 0), (2, 1.9999)])
def test_short_and_edge_climaxes(tmp_path, length, climax):
    bed = pick_or_generate("chill", length, climax, output_dir=tmp_path)
    assert len(pcm(bed.path)) == round(length * SAMPLE_RATE)
    assert bed.sections[1].start == climax
    assert all(s.start <= s.end for s in bed.sections)


@pytest.mark.parametrize("kwargs", [
    {"length": 0}, {"length": -1}, {"length": 601}, {"length": float("nan")},
    {"climax_at": -1}, {"climax_at": 4}, {"climax_at": float("inf")},
    {"bpm": 0}, {"bpm": 241}, {"bpm": True}, {"bpm": "120"},
    {"style": "unknown"}, {"style": None}, {"mode": ""}, {"seed": -1},
])
def test_invalid_requests(tmp_path, kwargs):
    args = dict(style="chill", length=4, climax_at=1, output_dir=tmp_path)
    args.update(kwargs)
    with pytest.raises(ValueError):
        pick_or_generate(**args)
    assert not list(tmp_path.glob("*.wav"))


def click_track(path, bpm=120, duration=12):
    samples = np.zeros(round(duration * SAMPLE_RATE))
    t = np.arange(round(.05 * SAMPLE_RATE)) / SAMPLE_RATE
    click = .8 * np.sin(2 * np.pi * 1000 * t) * np.exp(-t * 60)
    for start in np.arange(0, duration - .05, 60 / bpm):
        i = round(start * SAMPLE_RATE)
        samples[i:i + len(click)] += click
    write_audio(path, samples)
    return samples


@pytest.mark.parametrize("bpm", [40, 60, 85, 100, 120, 140, 180, 220, 240])
def test_fallback_tempo(tmp_path, bpm):
    path = tmp_path / "clicks.wav"
    click_track(path, bpm)
    result = analyze_track(path, use_librosa=False)
    assert result.method == "autocorrelation"
    assert result.bpm == pytest.approx(bpm, abs=3)
    assert result.duration == 12
    assert 0 < result.energy < 1


def test_optional_librosa_missing_and_broken(tmp_path, monkeypatch):
    path = tmp_path / "clicks.wav"
    click_track(path)
    original = builtins.__import__
    for error in (ImportError("not installed"), RuntimeError("binary incompatibility")):
        def unavailable(name, *args, **kwargs):
            if name == "librosa":
                raise error
            return original(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", unavailable)
        result = analyze_track(path)
        assert result.method == "autocorrelation"
        assert result.bpm == pytest.approx(120, abs=3)


def test_optional_librosa_result(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    path = tmp_path / "clicks.wav"
    click_track(path)
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace(
        beat=SimpleNamespace(beat_track=lambda **kw: (np.array([121.]), np.array([])))))
    report = analyze_track(path)
    assert report.method == "librosa" and report.bpm == 121


def test_silence_short_steady_and_invalid():
    for samples in (np.zeros(SAMPLE_RATE * 3), np.ones(100), np.ones(SAMPLE_RATE * 3) * .1):
        assert analyze_samples(samples, use_librosa=False).bpm is None
    for samples in (np.array([]), np.array([np.nan]), np.zeros((2, 2))):
        with pytest.raises(ValueError):
            analyze_samples(samples)


@pytest.fixture
def library(tmp_path):
    click_track(tmp_path / "hype.wav")
    click_track(tmp_path / "calm.wav", 85)
    data = {"version": 1, "tracks": [
        {"path": "hype.wav", "energy": .9, "mood": ["hype"], "bpm": 120,
         "license": "CC0-1.0", "styles": ["energetic"], "modes": ["highlight"],
         "drop_at": 2, "attribution": "Synthetic test fixture"},
        {"path": "calm.wav", "energy": .2, "mood": ["calm"], "bpm": 85,
         "license": "User supplied license", "styles": ["chill"], "modes": ["lowlight"]},
    ]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path, data


def test_manifest_selection_and_fallback(library, tmp_path):
    path, _ = library
    tracks = load_manifest(path)
    assert select_track(tracks, "energetic", "highlight").path.name == "hype.wav"
    assert select_track(tracks, "chill", "lowlight").path.name == "calm.wav"
    assert select_track(tracks, "chill", "highlight") is None
    bed = pick_or_generate("chill", 5, 2, manifest=path, mode="highlight", output_dir=tmp_path)
    assert bed.source == "procedural"


def test_library_render_alignment_and_provenance(library, tmp_path):
    path, _ = library
    bed = pick_or_generate("energetic", 16.123, 3.137, manifest=path,
                           mode="HIGHLIGHT", bpm=180, output_dir=tmp_path)
    assert bed.bpm == 120  # never mislabel or silently time-stretch a recording
    assert bed.license == "CC0-1.0"
    assert bed.attribution == "Synthetic test fixture"
    assert bed.source.endswith("hype.wav")
    assert bed.sections[1].start == 3.137
    samples = pcm(bed.path)
    assert len(samples) == round(16.123 * SAMPLE_RATE)
    # Source click at drop_at=2 must actually occur at the requested climax.
    drop = round(3.137 * SAMPLE_RATE)
    assert np.max(abs(samples[drop:drop + 1000])) > .5
    assert np.max(abs(samples[drop - 1000:drop])) < .001
    assert analyze_samples(samples, use_librosa=False).bpm == pytest.approx(120, abs=3)


def test_library_without_bpm(library, tmp_path):
    path, data = library
    data["tracks"][0]["bpm"] = None
    path.write_text(json.dumps(data))
    bed = pick_or_generate("energetic", 8, 3, manifest=path, output_dir=tmp_path)
    assert bed.bpm == pytest.approx(120, abs=3)


@pytest.mark.parametrize("field,value", [
    ("license", ""), ("energy", 2), ("energy", "high"), ("bpm", -10),
    ("mood", "calm"), ("styles", [None]), ("path", "missing.wav"),
    ("drop_at", -1), ("attribution", 123),
])
def test_bad_manifest(library, field, value):
    path, data = library
    data["tracks"][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manifest(path)


@pytest.mark.parametrize("data", [{}, [], {"version": 2, "tracks": []}, {"version": 1, "tracks": [None]}])
def test_bad_manifest_shape(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manifest(path)


def test_invalid_library_audio(library, tmp_path):
    path, data = library
    data["tracks"][0]["drop_at"] = 50
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="drop_at"):
        pick_or_generate("energetic", 5, 2, manifest=path, output_dir=tmp_path)
    data["tracks"][0]["drop_at"] = 0
    data["tracks"][0]["bpm"] = None
    path.write_text(json.dumps(data))
    write_audio(tmp_path / "hype.wav", np.zeros(SAMPLE_RATE * 3))
    with pytest.raises(ValueError, match="provide bpm"):
        pick_or_generate("energetic", 5, 2, manifest=path, output_dir=tmp_path)


def test_ffmpeg_formats_and_decode_errors(tmp_path):
    path = tmp_path / "synthetic.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", "-ac", "2", str(path)],
                   check=True, capture_output=True, timeout=30)
    result = analyze_track(path, use_librosa=False)
    assert result.duration == pytest.approx(3, abs=.01)
    assert result.energy > 0
    with pytest.raises(FileNotFoundError):
        read_audio(tmp_path / "missing.wav")
    path.write_bytes(b"not audio")
    with pytest.raises(ValueError, match="Unable to decode"):
        read_audio(path)


def test_manifest_ranking_and_empty_fallback(library, tmp_path):
    path, data = library
    for entry in data["tracks"]:
        entry["styles"] = []
        entry["modes"] = []
    path.write_text(json.dumps(data))
    tracks = load_manifest(path)
    assert select_track(tracks, "energetic").path.name == "hype.wav"
    assert select_track(tracks, "chill").path.name == "calm.wav"
    path.write_text(json.dumps({"version": 1, "tracks": []}))
    bed = pick_or_generate("chill", 3, 1, manifest=path, output_dir=tmp_path)
    assert bed.source == "procedural"


def test_decoder_missing_ffmpeg(tmp_path, monkeypatch):
    path = tmp_path / "track.wav"
    click_track(path)

    def missing(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="ffmpeg is required"):
        read_audio(path)


def test_music_bed_in_existing_renderer(video, tmp_path, monkeypatch):
    from render import RenderPlan
    from render.engine import probe
    from services.ffmpeg_runner import FFmpegRunner

    monkeypatch.setattr("services.ffmpeg_runner.HAS_NVENC", False)
    bed = pick_or_generate("energetic", 2, 1, output_dir=tmp_path)
    plan = RenderPlan(segments=[dict(source_start=0, source_end=2)],
                      resolution=720, fps=10,
                      music=dict(path=str(bed.path), beats=bed.beats, duck=True))
    output = FFmpegRunner(tmp_path / "render", video, 160, 120, 10).render(plan.model_dump())
    info = probe(output)
    assert abs(float(info["format"]["duration"]) - 2) < .15
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert audio["codec_name"] == "aac"
    assert audio["channels"] == 2
    assert audio["sample_rate"] == "48000"
