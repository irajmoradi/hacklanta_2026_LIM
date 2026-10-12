import base64
import importlib
import io
import sys
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import MagicMock

import numpy as np
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from gpu.models import Engine, rle
from gpu.schemas import MODEL_ID, REQUESTS, decode, validate_response
from gpu.server import create_api


def b64(data):
    return base64.b64encode(data).decode()


def png(width=4, height=3):
    stream = io.BytesIO()
    Image.new("RGB", (width, height)).save(stream, format="PNG")
    return b64(stream.getvalue())


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("GPU_API_TOKEN", "test-token")
    calls = []

    async def infer(kind, payload):
        calls.append((kind, payload))
        if kind == "segment":
            return {"mask": [[0, 1, 0, 0]] * 3}
        if kind == "transcribe":
            return {"words": [{"start": 0, "end": .5, "text": "go", "probability": .9}], "language": "en"}
        if kind == "embed":
            return {"features": [0.] * 1024, "encoder": payload["encoder"]}
        return {"width": 4, "height": 3, "frames": [
            {"frame_index": i, "time": i/payload["fps"], "objects": []}
            for i in range(len(payload["frames_png"]))]}

    return TestClient(create_api(infer)), calls


HEADERS = {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize("kind,payload", [
    ("segment", {"image_png": png(), "prompt": "player"}),
    ("track", {"frames_png": [png(), png()], "fps": 4, "prompt": "enemy"}),
    ("transcribe", {"pcm_f32le": b64(np.zeros(16000, "<f4").tobytes())}),
    ("embed", {"rgb_u8": b64(bytes(16*256*256*3)), "frames": 16, "encoder": "test"}),
])
def test_valid_contracts(gateway, kind, payload):
    client, calls = gateway
    response = client.post("/" + kind, json=payload, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert len(calls) == 1


@pytest.mark.parametrize("kind,payload", [
    ("segment", {"image_png": "bad", "prompt": "player"}),
    ("segment", {"image_png": png(257), "prompt": "player"}),
    ("segment", {"image_png": png(), "prompt": " "}),
    ("segment", {"image_png": png(), "prompt": "x", "url": "https://example.com"}),
    ("track", {"frames_png": [png(), png(3)], "fps": 4, "prompt": "x"}),
    ("track", {"frames_png": [png(), png()], "fps": .01, "prompt": "x"}),
    ("transcribe", {"pcm_f32le": b64(np.array([np.nan], "<f4").tobytes())}),
    ("transcribe", {"pcm_f32le": b64(bytes(61*16000*4))}),
    ("transcribe", {"pcm_f32le": b64(bytes(9))}),
    ("embed", {"rgb_u8": b64(bytes(16)), "frames": 17, "encoder": "x"}),
])
def test_rejected_before_gpu(gateway, kind, payload):
    client, calls = gateway
    assert client.post("/" + kind, json=payload, headers=HEADERS).status_code == 422
    assert not calls


def test_auth_size_and_error_redaction(gateway, monkeypatch):
    client, calls = gateway
    assert client.post("/segment", json={}).status_code == 401
    monkeypatch.delenv("GPU_API_TOKEN")
    assert client.post("/segment", json={}, headers=HEADERS).status_code == 401
    monkeypatch.setenv("GPU_API_TOKEN", "test-token")
    monkeypatch.setattr("gpu.server.MAX_BODY", 10)
    assert client.post("/segment", content=b"x"*11, headers={**HEADERS, "Content-Type": "application/json"}).status_code == 413
    assert not calls

    async def broken(*args):
        raise RuntimeError("private-token-media")

    monkeypatch.setattr("gpu.server.MAX_BODY", 1024)
    response = TestClient(create_api(broken)).post("/segment", json={"image_png": png(), "prompt": "x"}, headers=HEADERS)
    assert response.status_code == 503
    assert "private" not in response.text


def test_reject_bad_model_output(monkeypatch):
    monkeypatch.setenv("GPU_API_TOKEN", "test-token")
    async def broken(*args):
        return {"mask": [[2]]}
    client = TestClient(create_api(broken))
    assert client.post("/segment", json={"image_png": png(), "prompt": "x"}, headers=HEADERS).status_code == 503


def test_rle_tracking_and_cleanup():
    engine = Engine()
    mask = np.array([[0, 1], [1, 0]])
    assert rle(mask) == [1, 2, 1]
    assert rle(np.ones((2, 2))) == [0, 4]
    predictor = MagicMock()
    predictor.handle_request.return_value = {"session_id": "s"}
    predictor.handle_stream_request.return_value = iter([
        {"frame_index": i, "outputs": {"out_obj_ids": [7], "out_binary_masks": [mask]}}
        for i in range(2)])
    engine.model = predictor
    request = REQUESTS["track"](frames_png=[png(2, 2)]*2, fps=2, prompt="player")
    frames = decode("track", request)
    result = engine.track(frames, request)
    validate_response("track", result, request, frames)
    assert result["frames"][1]["objects"][0]["id"] == 7
    assert predictor.handle_request.call_args.args[0]["type"] == "close_session"
    predictor.handle_stream_request.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError):
        engine.track(frames, request)
    assert predictor.handle_request.call_args.args[0]["type"] == "close_session"


def test_modal_definition_with_mock(monkeypatch):
    options = []
    def decorator(**kwargs):
        options.append(kwargs)
        return lambda value: value
    image = MagicMock()
    for name in ("pip_install", "apt_install", "env", "add_local_python_source"):
        getattr(image, name).return_value = image
    app = SimpleNamespace(cls=decorator, function=decorator)
    modal = SimpleNamespace(App=lambda *a: app, Image=SimpleNamespace(debian_slim=lambda **kw: image),
                            Secret=MagicMock(), Volume=MagicMock(), enter=decorator,
                            method=decorator, asgi_app=decorator)
    monkeypatch.setitem(sys.modules, "modal", modal)
    monkeypatch.setenv("VJEPA_REVISION", "a"*40)
    sys.modules.pop("gpu.modal_app", None)
    module = importlib.import_module("gpu.modal_app")
    worker = next(option for option in options if "gpu" in option)
    assert worker["min_containers"] == 0 and worker["max_containers"] == 1
    assert worker["scaledown_window"] == 30 and worker["retries"] == 0
    assert module.app is app
    sys.modules.pop("gpu.modal_app", None)


def test_whisper_runner_consumes_words_and_requests_timestamps():
    engine = Engine()
    engine.family = "transcribe"
    engine.model = MagicMock()
    word = SimpleNamespace(start=.1, end=.3, word=" go ", probability=.8)
    engine.model.transcribe.return_value = (iter([SimpleNamespace(words=[word])]),
                                            SimpleNamespace(language="en"))
    result = engine.infer("transcribe", {"pcm_f32le": b64(np.zeros(16000, "<f4").tobytes())})
    assert result["words"][0]["text"] == "go"
    assert engine.model.transcribe.call_args.kwargs == {"word_timestamps": True, "vad_filter": True}


def test_embedding_runner_pools_without_resampling(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    engine = Engine()
    engine.family = "embed"
    engine.identity = "test"
    engine.model = MagicMock()
    output = engine.model.get_vision_features.return_value
    output.mean.return_value.float.return_value.cpu.return_value.numpy.return_value = np.ones((1, 1024))
    engine.processor = MagicMock()
    engine.processor.return_value.to.return_value = {"pixel_values_videos": "sentinel"}
    result = engine.infer("embed", {"rgb_u8": b64(bytes(16*256*256*3)), "frames": 16, "encoder": "test"})
    assert result["features"] == [1.]*1024
    output.mean.assert_called_once_with(dim=1)
    assert engine.processor.call_args.kwargs["do_sample_frames"] is False
    engine.model.get_vision_features.assert_called_once_with(pixel_values_videos="sentinel")


@pytest.mark.parametrize("kind,result,values", [
    ("transcribe", {"words": [{"start": 0, "end": 2, "text": "x", "probability": .5}]},
     {"pcm_f32le": b64(bytes(16000*4))}),
    ("transcribe", {"words": [{"start": 0, "end": .5, "text": "x", "probability": float("nan")}]},
     {"pcm_f32le": b64(bytes(16000*4))}),
    ("embed", {"features": [0.]*1024, "encoder": "wrong"},
     {"frames": 16, "encoder": "test", "rgb_u8": b64(bytes(16*256*256*3))}),
])
def test_response_contract_rejections(kind, result, values):
    request = REQUESTS[kind].model_validate(values)
    with pytest.raises(ValueError):
        validate_response(kind, result, request, decode(kind, request))
