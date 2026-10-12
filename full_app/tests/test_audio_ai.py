"""Synthetic media only; model APIs are mocked and never download weights."""

import json
import shutil
import subprocess
import sys
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from audio_ai import AudioSignals, Word, analyze
from audio_ai import backends

RATE = 16000


def run(*args):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True)


def write_wav(path, samples):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio-signals")
    t = np.arange(RATE) / RATE
    rng = np.random.default_rng(11)
    sound = np.zeros(round(7.25 * RATE))
    sound[RATE:2 * RATE] = .12 * np.sin(2 * np.pi * 800 * t)
    # Four laughter-like noisy syllables, each 120 ms, separated by silence.
    sound[2 * RATE:3 * RATE] = .6 * rng.uniform(-1, 1, RATE) * ((t % .25) < .12)
    sound[3 * RATE:4 * RATE] = .65 * np.sin(2 * np.pi * 900 * t)
    sound[4 * RATE:5 * RATE] = .8 * rng.uniform(-1, 1, RATE)
    sound[5 * RATE:6 * RATE] = .85 * rng.uniform(-1, 1, RATE) * ((t % .1) < .018)
    wav = write_wav(path / "pattern.wav", sound)
    video = path / "pattern.mkv"
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=64x64:rate=20:duration=7.25", "-i", wav,
        "-c:v", "mpeg4", "-c:a", "pcm_s16le", video)
    return video, wav


def offline(path, **kwargs):
    return analyze(path, speech="off", vad="energy", **kwargs)


def test_synthetic_event_timing_and_fusion_shape(synthetic):
    result = offline(synthetic[0])
    assert result.duration == pytest.approx(7.25, abs=.01)
    assert len(result.seconds) == 8
    assert result.seconds[-1].end == pytest.approx(7.25, abs=.01)
    expected = {"laugh": 2, "shout": 3, "cheer": 4, "gunfire": 5}
    for kind, second in expected.items():
        assert any(e.type == kind and e.start <= second < e.end for e in result.events), (kind, result.events)
    assert [(e.start, e.end) for e in result.events if e.type == "silence"] == [(0, 1), (6, 7.25)]
    assert result.seconds[0].signals["audio_voice_share"] == 0
    assert result.seconds[0].signals["audio_game_share"] == 0
    assert result.seconds[1].signals["audio_voice_share"] > .95
    assert result.seconds[4].signals["audio_game_share"] > .5
    payload = json.loads(result.model_dump_json())
    assert AudioSignals.model_validate(payload) == result
    for row in payload["seconds"]:
        assert {"start", "end", "score", "signals", "events"} <= row.keys()
        assert all(np.isfinite(x) for x in row["signals"].values())
        assert 0 <= row["score"] <= 1
        for event in row["events"]:
            assert event["start"] < row["end"] and event["end"] > row["start"]


def test_no_audio_and_track_validation(tmp_path):
    video = tmp_path / "silent.mkv"
    run("ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=size=64x64:rate=10:duration=1.3", "-an", "-c:v", "mpeg4", video)
    result = analyze(video)
    assert len(result.seconds) == 2
    assert result.events[0].type == "silence"
    assert result.events[0].end == pytest.approx(1.3)
    assert result.warnings
    with pytest.raises(ValueError, match="does not exist"):
        offline(video, audio_track=1)


def test_optional_failures_preserve_baseline(synthetic, monkeypatch):
    def unavailable(*args):
        raise ImportError("optional dependency absent")
    for name in ("transcribe", "classify", "speech_activity"):
        monkeypatch.setattr(backends, name, unavailable)
    baseline = offline(synthetic[1])
    result = analyze(synthetic[1], speech="whisper", vad="webrtc", events="yamnet", separator=unavailable)
    assert result.seconds == baseline.seconds
    assert result.words == []
    assert len(result.warnings) == 4
    assert result.backends == baseline.backends


def test_word_timestamps_phrases_and_classifier(synthetic, monkeypatch):
    monkeypatch.setattr(backends, "transcribe", lambda *args: [
        Word(start=1.8, end=1.95, text="LET’S", probability=.9),
        Word(start=2.02, end=2.2, text="GO!", probability=.8),
        Word(start=3.1, end=3.3, text="bro,"),
        Word(start=4.1, end=4.3, text="shit"),
        Word(start=5.1, end=5.3, text="clutch"),
    ])
    monkeypatch.setattr(backends, "classify", lambda *args: [
        (3.84, 4.8, {"laugh": .91, "cheer": .2, "shout": .1, "gunfire": .05})])
    result = analyze(synthetic[1], vad="energy", events="yamnet", yamnet_model="mock")
    phrase = next(e for e in result.events if e.text == "lets go")
    assert (phrase.start, phrase.end, phrase.score, phrase.cue) == (1.8, 2.2, .8, "excitement")
    assert result.seconds[1].signals["audio_hype_phrase"] == .8
    assert result.seconds[2].signals["audio_hype_phrase"] == .8
    assert result.seconds[2].signals["audio_laugh"] == 0  # classifier replaces heuristics
    assert result.seconds[4].signals["audio_laugh"] == .91
    assert result.backends["speech"] == "faster-whisper"
    assert result.backends["events"] == "yamnet"


def test_phrase_boundaries_and_long_gaps():
    words = [Word(start=0, end=.1, text="no"), Word(start=2, end=2.1, text="way"),
             Word(start=3, end=3.1, text="broccoli"), Word(start=4, end=4.2, text="No way!")]
    events = backends.phrase_events(words)
    assert len(events) == 1
    assert events[0].start == 4
    assert events[0].cue == "surprise"


def test_short_tail_and_digital_silence(tmp_path):
    path = write_wav(tmp_path / "tiny.wav", np.zeros(37))
    result = offline(path)
    assert len(result.seconds) == 1
    assert result.duration == pytest.approx(37 / RATE, abs=1e-6)
    assert result.seconds[0].signals["audio_silence"] == 1
    assert result.seconds[0].signals["audio_loudness_dbfs"] == -120


def test_stem_hook_and_bad_output(synthetic):
    result = offline(synthetic[1], separator=lambda x, rate: (x, np.zeros_like(x)))
    assert result.backends["separation"] == "separator_hook"
    assert result.seconds[4].signals["audio_voice_share"] > .99
    result = offline(synthetic[1], separator=lambda x, rate: (x[:-1], x))
    assert result.backends["separation"] == "band_energy"
    assert result.warnings


def test_multitrack_and_delayed_audio(tmp_path):
    video = tmp_path / "tracks.mkv"
    run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=3",
        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=3",
        "-itsoffset", "1", "-f", "lavfi", "-i", "sine=frequency=800:sample_rate=16000:duration=1",
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "pcm_s16le", video)
    mixed = offline(video)
    mic = offline(video, audio_track=1)
    assert all(row.signals["audio_silence"] == 1 for row in mixed.seconds)
    assert mic.seconds[0].signals["audio_silence"] == 1
    assert mic.seconds[1].signals["audio_speech_activity"] > .95
    assert mic.seconds[2].signals["audio_silence"] == 1
    with pytest.raises(ValueError):
        offline(video, audio_track=2)


def test_cli_json(synthetic):
    result = run(sys.executable, "-m", "audio_ai", synthetic[1], "--speech", "off", "--vad", "energy")
    assert len(json.loads(result.stdout)["seconds"]) == 8


@pytest.mark.parametrize("kwargs", [{"audio_track": -1}, {"audio_track": True}, {"speech": "bad"},
                                  {"vad": "bad"}, {"events": "bad"}, {"silence_db": float("nan")}])
def test_invalid_options(synthetic, kwargs):
    with pytest.raises(ValueError):
        analyze(synthetic[1], **kwargs)


def test_invalid_media_is_not_silence(tmp_path):
    path = tmp_path / "broken.wav"
    path.write_text("not media")
    with pytest.raises(subprocess.CalledProcessError):
        offline(path)
    with pytest.raises(FileNotFoundError):
        offline(tmp_path / "missing.wav")


def test_generated_speech_if_available(tmp_path):
    engine = shutil.which("espeak-ng") or shutil.which("espeak")
    if not engine:
        pytest.skip("espeak-ng/espeak unavailable; no prerecorded speech is downloaded")
    voice = tmp_path / "speech.wav"
    run(engine, "-w", voice, "No way, bro! Let's go! That was clutch!")
    padded = tmp_path / "padded.wav"
    run("ffmpeg", "-v", "error", "-i", voice, "-af", "adelay=1000,apad=pad_dur=1", padded)
    result = offline(padded)
    assert result.seconds[0].signals["audio_silence"] == 1
    assert max(row.signals["audio_speech_activity"] for row in result.seconds[1:]) > .5
    assert result.seconds[-1].signals["audio_silence"] == 1


def test_whisper_adapter_is_cpu_cached_and_word_level(monkeypatch):
    calls = {}
    class FakeWhisper:
        def __init__(self, model, **kwargs):
            calls.update(model=model, **kwargs)
        def transcribe(self, samples, **kwargs):
            calls.update(kwargs)
            word = SimpleNamespace(start=.2, end=.4, word=" bro", probability=.9)
            return iter([SimpleNamespace(words=[word])]), None
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisper))
    assert backends.transcribe(np.zeros(RATE, np.float32))[0].text == "bro"
    assert calls == dict(model="tiny", device="cpu", compute_type="int8", local_files_only=True,
                         word_timestamps=True, vad_filter=True)


def test_webrtc_adapter_pcm_frames(monkeypatch):
    calls = []
    class FakeVAD:
        def __init__(self, mode):
            assert mode == 2
        def is_speech(self, frame, rate):
            assert len(frame) == 640 and rate == RATE
            calls.append(frame)
            return any(frame)
    monkeypatch.setitem(sys.modules, "webrtcvad", SimpleNamespace(Vad=FakeVAD))
    result = backends.speech_activity(np.ones(321, dtype=np.float32) * .1)
    assert result.tolist() == [1, 1]
    assert len(calls) == 2


def test_yamnet_adapter_labels_hops_and_chunking(tmp_path, monkeypatch):
    mapping = tmp_path / "classes.csv"
    mapping.write_text('index,mid,display_name\n0,/a,Laughter\n1,/b,Cheering\n2,/c,"Gunshot, gunfire"\n')
    class FakeModel:
        def class_map_path(self):
            return SimpleNamespace(numpy=lambda: str(mapping).encode())
        def __call__(self, samples):
            assert len(samples) >= 15600
            data = np.tile([.9, .2, .7], (51, 1))
            return SimpleNamespace(numpy=lambda: data), None, None
    monkeypatch.setitem(sys.modules, "tensorflow_hub", SimpleNamespace(load=lambda path: FakeModel()))
    result = backends.classify(np.zeros(25 * RATE, np.float32), tmp_path)
    assert result[1][0] == .48
    assert result[50][0] == 24
    assert result[-1][1] == 25
    assert result[0][2] == {"laugh": .9, "shout": 0, "cheer": .2, "gunfire": .7}
