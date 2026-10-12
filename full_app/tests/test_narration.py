import array
import io
import math
import subprocess
from types import SimpleNamespace
import wave

import pytest

import narration
from narration import providers


CLIPS = [{"start": 10, "end": 22, "peak_time": 16, "caption": "A clutch win"}]
PLAN = {"segments": [{"source_start": 10, "source_end": 22, "speed": 2}],
        "reaction_overlays": [{"start": 2, "end": 4}]}


@pytest.fixture(autouse=True)
def clear_keys(monkeypatch):
    for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "NARRATION_CONSENTED_VOICE_ID", "ELEVENLABS_VOICE_ID"):
        monkeypatch.delenv(key, raising=False)


def test_offline_timing_and_personas(tmp_path):
    for persona in narration.PERSONAS:
        track = narration.build(CLIPS, PLAN, persona, cache_dir=tmp_path)
        assert track.duration == 6
        assert track.segments
        assert track == narration.build(CLIPS, PLAN, persona, cache_dir=tmp_path)
        for s in track.segments:
            assert 0 <= s.start < s.end <= 6
            assert s.end <= 1.9 or s.start >= 4.1
            assert s.audio_file is None


def test_no_keys_network_opt_in(tmp_path):
    track = narration.build(CLIPS, PLAN, allow_network=True, cache_dir=tmp_path)
    assert track.segments and track.segments[0].audio_file is None


def test_mock_gemini_and_cap(monkeypatch, tmp_path):
    calls = []
    def script(context, persona):
        assert context[0]["caption"] == "A clutch win"
        return ["Perfect aim wins this round"] * len(context)
    monkeypatch.setattr(providers, "gemini_script", script)
    monkeypatch.setattr(providers, "synthesize", lambda text, *a, **k: calls.append(text))
    plan = {"segments": PLAN["segments"] * 3}
    track = narration.build(CLIPS, plan, allow_network=True, character_cap=30, cache_dir=tmp_path)
    assert sum(map(len, calls)) == track.characters <= 30
    assert track.segments[0].text == "Perfect aim wins this round"
    assert not narration.build(CLIPS, plan, character_cap=0).segments


def test_provider_failures(monkeypatch, tmp_path):
    def fail(*a, **kw):
        raise RuntimeError("secret must not leak")
    monkeypatch.setattr(providers, "gemini_script", fail)
    monkeypatch.setattr(providers, "synthesize", fail)
    track = narration.build(CLIPS, PLAN, allow_network=True, cache_dir=tmp_path)
    assert len(track.warnings) == 2
    assert "secret" not in repr(track)
    assert track.segments[0].text.startswith("What a play")


@pytest.mark.parametrize("vertex", [False, True])
def test_gemini_request_and_validation(monkeypatch, vertex):
    from google import genai
    calls = []
    payload = ['["A clean win"]']
    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text=payload[0])

    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", str(vertex).lower())
    monkeypatch.setenv("GOOGLE_API_KEY" if vertex else "GEMINI_API_KEY", "fake")
    context = [{"caption": "A win", "max_words": 5}]
    assert providers.gemini_script(context, "hype_caster") == ["A clean win"]
    assert calls[0]["vertexai"] is vertex
    assert calls[0]["api_key"] == "fake"
    assert "A win" in calls[1]["contents"]
    for invalid in ('{}', '[]', '[null]', '[""]', 'not json'):
        payload[0] = invalid
        with pytest.raises(ValueError):
            providers.gemini_script(context, "hype_caster")


def test_tts_cache_and_voice_consent(monkeypatch, tmp_path):
    calls = []
    def request(req, timeout):
        calls.append(req)
        assert timeout == 30
        assert req.get_header("Xi-api-key") == "fake"
        return io.BytesIO(b"\x00\x01" * 24000)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "unconsented")
    monkeypatch.setattr(providers, "urlopen", request)
    voice = providers.voice_id()
    assert voice == providers.STOCK_VOICE
    a = providers.synthesize("Great play", voice, tmp_path, allow_network=True)
    assert providers.wav_duration(a) == 1
    assert providers.synthesize("Great play", voice, tmp_path) == a
    assert len(calls) == 1
    monkeypatch.setenv("NARRATION_CONSENTED_VOICE_ID", "consented")
    providers.synthesize("Great play", providers.voice_id(), tmp_path, allow_network=True)
    providers.synthesize("Other text", voice, tmp_path, allow_network=True)
    assert len(calls) == 3  # All HTTP calls mocked.
    a.write_bytes(b"corrupt")
    assert providers.synthesize("Great play", voice, tmp_path) is None
    monkeypatch.setenv("NARRATION_CONSENTED_VOICE_ID", "../bad")
    with pytest.raises(ValueError):
        providers.voice_id()


def test_audio_duration_protects_reactions(monkeypatch, tmp_path):
    path = tmp_path / "long.wav"
    with wave.open(str(path), "wb") as w:
        w.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        w.writeframes(b"\x00\x00" * 24000 * 5)
    monkeypatch.setattr(providers, "synthesize", lambda *a, **kw: path)
    track = narration.build(CLIPS, PLAN)
    assert not track.segments
    assert "exceeds" in track.warnings[0]


def test_speed_effects_and_fully_blocked():
    plan = {"segments": [{"source_start": 10, "source_end": 22, "speed": 2,
                           "video_effects": ["slow_motion"]}],
            "reaction_overlays": [{"start": 0, "end": 12}]}
    track = narration.build(CLIPS, plan)
    assert track.duration == 12 and not track.segments


@pytest.mark.parametrize("field,value", [("speed", 0), ("source_end", 9), ("speed", float("nan"))])
def test_invalid_timeline(field, value):
    segment = dict(PLAN["segments"][0], **{field: value})
    with pytest.raises(ValueError):
        narration.build(CLIPS, {"segments": [segment]})


def test_existing_models():
    from models.schemas import Clip, EditPlan, EditSegment
    clip = Clip(start=0., end=6., start_seconds=0., end_seconds=6., type="good", description="A win")
    plan = EditPlan(segments=[EditSegment(source_start=0, source_end=6)])
    assert narration.build([clip], plan).duration == 6


def amplitude(path, start, frequency):
    result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path),
                             "-t", "0.25", "-vn", "-ac", "1", "-ar", "24000", "-f", "f32le", "-"],
                            capture_output=True, check=True)
    samples = array.array("f", result.stdout)
    return abs(sum(x * complex(math.cos(2*math.pi*frequency*i/24000),
                              math.sin(2*math.pi*frequency*i/24000))
                   for i, x in enumerate(samples))) / len(samples)


def test_render_ducks_and_mixes(video, tmp_path):
    voice = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=1:sample_rate=24000", str(voice)], check=True)
    track = narration.NarrationTrack([narration.NarrationSegment(2, 3, "Great play", voice)], 6)
    assert "volume=0.25:enable=" in narration.filter_graph(track)
    output = narration.render(video, track, tmp_path / "mixed.mp4")
    assert amplitude(output, 2.3, 440) < amplitude(output, 1, 440) * 0.4
    assert amplitude(output, 2.3, 880) > amplitude(output, 1, 880) * 10
    assert amplitude(output, 4, 440) > amplitude(output, 2.3, 440) * 3
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-an", "-c:v", "copy", str(silent)], check=True)
    assert narration.render(silent, track, tmp_path / "voiced.mp4").exists()
    assert narration.render(video, narration.NarrationTrack(), tmp_path / "unused.mp4") == video.resolve()
    with pytest.raises(ValueError):
        narration.render(video, track, video)
