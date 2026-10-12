"""Exercise real adapters/media and fake SDK inference boundaries without credentials."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from eval.dataset import load_dataset
from eval.metrics import interval
from eval.pipelines import GeminiOnly, GenerationBudget, Unavailable, local_window_scorer, signals_only, signals_vlm
from eval.runner import evaluate
from eval.synthetic import generate
from signals import Candidate


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    return load_dataset(generate(tmp_path_factory.mktemp("eval-adapters")))


def fake_sdk(error=None):
    uploaded = SimpleNamespace(name="files/fake", uri="https://example.invalid/fake",
                               mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE"))
    sdk = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(
        return_value=SimpleNamespace(text='{"clips": []}'), side_effect=error)),
        files=SimpleNamespace(upload=Mock(return_value=uploaded),
                              get=Mock(return_value=uploaded), delete=Mock()), close=Mock())
    return sdk


def test_real_signals_nonempty(media):
    assert interval(Candidate(0, 1, 2, {}), 2) == dict(start=0, end=1, score=2)
    result = evaluate(media, {"signals": signals_only})["pipelines"]["signals"]
    assert result["status"] == "ok"
    assert result["videos"][0]["prediction_count"] > 0


@pytest.mark.parametrize("error", [None, TimeoutError("retryable"), ValueError("bad response")])
def test_sdk_attempt_budget_and_file_cleanup(media, monkeypatch, error):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    sdk = fake_sdk(error)
    adapter = GeminiOnly(client=sdk)
    for _ in range(3):
        if error:
            with pytest.raises(type(error)):
                adapter(media[0])
        else:
            assert adapter(media[0])["clips"] == []
    with pytest.raises(Unavailable, match="budget"):
        adapter(media[0])
    assert sdk.models.generate_content.call_count == adapter.calls == 3
    assert sdk.files.upload.call_count == sdk.files.delete.call_count == 3
    assert sdk.close.call_count == 3


def test_long_source_rejected_before_upload_even_with_short_manifest(media, monkeypatch):
    monkeypatch.setattr("services.video_understanding.video_duration", lambda *args: 1801)
    sdk = fake_sdk()
    adapter = GeminiOnly(client=sdk)
    with pytest.raises(Unavailable, match="single chunk"):
        adapter({**media[0], "duration_seconds": 1})
    assert adapter.calls == 0
    sdk.files.upload.assert_not_called()
    sdk.models.generate_content.assert_not_called()


def test_boundary_stops_accidental_chunk_or_retry_loop():
    budget = GenerationBudget()
    request = Mock(side_effect=TimeoutError())
    for _ in range(8):
        try:
            budget.invoke(request)
        except (TimeoutError, Unavailable):
            pass
    assert request.call_count == budget.calls == 3


def test_live_vertex_uses_one_sdk_attempt(media, monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    sdk = fake_sdk()
    factory = Mock(return_value=sdk)
    monkeypatch.setattr("google.genai.Client", factory)
    adapter = GeminiOnly(live_smoke=True)
    adapter(media[0])
    kwargs = factory.call_args.kwargs
    assert kwargs["vertexai"] is True
    assert kwargs["http_options"].retry_options.attempts == 1
    assert adapter.calls == 1
    sdk.files.upload.assert_not_called()
    sdk.close.assert_called_once()


def test_no_opt_in_and_missing_scorer_are_explicit_skips(media):
    with pytest.raises(Unavailable, match="disabled"):
        GeminiOnly()(media[0])
    with pytest.raises(Unavailable, match="No local window scorer"):
        signals_vlm(media[0])


def test_real_local_window_adapter_uses_current_provider(media, monkeypatch):
    from services.local_vlm import OpenAICompatibleVLMProvider
    monkeypatch.setenv("LOCAL_VLM_MODEL", "fake-local-model")
    monkeypatch.setenv("LOCAL_VLM_BASE_URL", "http://127.0.0.1:8000/v1")
    requests = []
    def transport(self, payload):
        requests.append(payload)
        return {"choices": [{"message": {"content": json.dumps(dict(
            player_alive=True, kind="highlight", hype=8.0, caption="burst", reaction="hype"))}}]}
    monkeypatch.setattr(OpenAICompatibleVLMProvider, "_post", transport)
    result = local_window_scorer(str(media[0]["path"]), [Candidate(1., 2., 2., {})])
    assert result == {"clips": [{"start": 1., "end": 2., "score": .8}], "cost_usd": 0.0}
    assert len(requests) == 1
    assert any(part["type"] == "image_url" for part in requests[0]["messages"][0]["content"])


def test_local_scorer_unconfigured_or_nonlocal(monkeypatch):
    monkeypatch.delenv("LOCAL_VLM_MODEL", raising=False)
    with pytest.raises(Unavailable, match="LOCAL_VLM_MODEL"):
        local_window_scorer("unused", [])
    monkeypatch.setenv("LOCAL_VLM_MODEL", "fake")
    monkeypatch.setenv("LOCAL_VLM_BASE_URL", "https://example.invalid/v1")
    with pytest.raises(Unavailable, match="loopback"):
        local_window_scorer("unused", [])
