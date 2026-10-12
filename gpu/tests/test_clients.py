import io
import json
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from gpu.clients import RemoteEncoder, Transport, transcribe
from gpu.schemas import MAX_RESPONSE
from gpu.server import create_api


def test_existing_sam_adapter(monkeypatch):
    from sam.backends import Config, RemoteSegmenter
    monkeypatch.setenv("GPU_API_TOKEN", "token")
    async def infer(kind, payload):
        assert kind == "segment" and payload["prompt"] == "enemy"
        return {"mask": [[0, 1], [1, 0]]}
    api = TestClient(create_api(infer))
    def open_request(request, timeout):
        response = api.post("/segment", content=request.data,
                            headers={key: value for key, value in request.header_items()})
        assert response.status_code == 200
        return io.BytesIO(response.content)
    monkeypatch.setattr("sam.backends.urlopen", open_request)
    mask = RemoteSegmenter(Config(backend="remote", url="https://test/segment", key="token")).segment(
        np.zeros((2, 2, 3), np.uint8), "enemy", None)
    assert mask.tolist() == [[0, 1], [1, 0]]


def test_audio_chunk_offsets_and_existing_analyzer(tmp_path, monkeypatch):
    from audio_ai import backends
    from audio_ai.analyzer import analyze
    monkeypatch.setenv("GPU_API_TOKEN", "token")
    monkeypatch.setenv("WHISPER_ENDPOINT_URL", "https://test/transcribe")
    calls = []
    def call(self, kind, payload):
        calls.append(kind)
        return {"words": [{"start": .1, "end": .3, "text": "bro", "probability": .9}]}
    monkeypatch.setattr(Transport, "call", call)
    words = transcribe(np.zeros(61*16000, np.float32))
    assert [word.start for word in words] == [.1, 60.1]
    assert calls == ["transcribe", "transcribe"]
    assert transcribe([]) == []
    path = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-ar", "16000", str(path)], check=True)
    monkeypatch.setattr(backends, "transcribe", transcribe)
    result = analyze(path, speech="whisper", vad="energy")
    assert result.words[0].text == "bro"
    assert any(event.type == "hype_phrase" for event in result.events)
    def failed(*args):
        raise RuntimeError("private")
    monkeypatch.setattr(Transport, "call", failed)
    result = analyze(path, speech="whisper", vad="energy")
    assert not result.words and result.warnings
    assert "private" not in str(result.warnings)


def test_encoder_in_existing_extract(tmp_path, monkeypatch):
    from vjepa.features import WindowConfig, extract
    monkeypatch.setenv("GPU_API_TOKEN", "token")
    monkeypatch.setenv("VJEPA_ENDPOINT_URL", "https://test/embed")
    monkeypatch.setenv("VJEPA_REVISION", "a"*40)
    calls = []
    def call(self, kind, payload):
        calls.append(kind)
        assert payload["frames"] == 16
        return {"features": [1.0]*1024, "encoder": payload["encoder"]}
    monkeypatch.setattr(Transport, "call", call)
    encoder = RemoteEncoder()
    video = tmp_path / "video.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=256x256:rate=8:duration=1",
                    "-c:v", "libx264", "-threads", "1", str(video)], check=True)
    config = WindowConfig(frames=16, resolution=256, fps=8, stride=2)
    data = extract(video, encoder, tmp_path / "cache", config)
    assert data["features"].shape == (1, 1024)
    assert data["encoder"] == encoder.identity
    extract(video, encoder, tmp_path / "cache", config)
    assert calls == ["embed"]
    with pytest.raises(ValueError):
        encoder.encode([np.zeros((16, 32, 32, 3), np.uint8)])


@pytest.mark.parametrize("url", ["http://test/embed", "https://token@test/embed", "https://test/embed?key=x"])
def test_transport_rejects_unsafe_url(url):
    with pytest.raises(ValueError):
        Transport(url, "token")


def test_transport_wire_and_validation(monkeypatch):
    payload = {"pcm_f32le": "AAAAAA=="}
    captured = []
    def open_request(request, timeout):
        captured.append(request)
        return io.BytesIO(json.dumps({"words": []}).encode())
    monkeypatch.setattr("gpu.clients.build_opener", lambda *a: SimpleNamespace(open=open_request))
    assert Transport("https://test/transcribe", "token").call("transcribe", payload) == {"words": []}
    assert captured[0].get_header("Authorization") == "Bearer token"
    def oversized(*args, **kwargs):
        return io.BytesIO(b"x"*(MAX_RESPONSE+1))
    monkeypatch.setattr("gpu.clients.build_opener", lambda *a: SimpleNamespace(open=oversized))
    with pytest.raises(RuntimeError, match="Remote GPU request failed"):
        Transport("https://test/transcribe", "token").call("transcribe", payload)
