import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError

from models.schemas import ClipList, ScoringCandidate, WindowAssessment
from services.gemini_client import GeminiProvider, GeminiVideoClient
from services.local_vlm import OpenAICompatibleVLMProvider
from services.video_understanding import (
    MockProvider, ProviderConfig, chunk_ranges, video_duration, video_slice,
)


def clip(start=0.5, end=1.5):
    return dict(start=start, end=end, start_seconds=start, end_seconds=end,
                type="good", description="Confirmed player elimination")


def assessment(**overrides):
    return dict(player_alive=True, kind="highlight", hype=8.0, caption="Clean finish",
                reaction="sick_kill", **overrides)


def candidate(start=1.0, end=3.0):
    return dict(start=start, end=end, score=1.5, signals={"motion": 2.0}, events=[])


def config(**kwargs):
    return ProviderConfig(backoff_seconds=0, **kwargs)


def sdk_client(responses=()):
    client = Mock()
    uploaded = SimpleNamespace(name="files/example", uri="https://example.invalid/video",
                               mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE"))
    client.files.upload.return_value = uploaded
    client.files.get.return_value = uploaded
    client.models.generate_content.side_effect = [
        SimpleNamespace(text=json.dumps(r), usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=10))
        if not isinstance(r, Exception) else r for r in responses
    ]
    return client


def test_chunk_ranges():
    assert list(chunk_ranges(1250, 600, 10)) == [(0, 600), (590, 1190), (1180, 1250)]
    assert list(chunk_ranges(600, 600, 10)) == [(0, 600)]
    with pytest.raises(ValueError):
        list(chunk_ranges(10, 10, 10))


def test_chunk_offsets_dedup_and_cleanup(video):
    provider = MockProvider([
        {"clips": [clip(2.1, 2.8)]},
        {"clips": [clip(0.1, 0.8), clip(1.0, 1.8)]},
        {"clips": [clip(0.5, 1.5)]},
    ], config(chunk_seconds=3, overlap_seconds=1))
    result = provider.analyze_video(video)
    assert [(c.start, c.end) for c in result.clips] == [(2.1, 2.8), (3, 3.8), (4.5, 5.5)]
    assert all(c.start == c.start_seconds and c.end == c.end_seconds for c in result.clips)
    assert all(not Path(call[0]).exists() for call in provider.calls)
    assert "TIMELINE OVERRIDE" in provider.calls[0][1]


def test_single_video_fallback(video):
    provider = MockProvider([{"clips": [clip()]}])
    assert len(provider.analyze_video(video).clips) == 1
    assert provider.calls[0][0] == str(video)


def test_clip_outside_chunk_rejected(video):
    provider = MockProvider([{"clips": [clip(0, 100)]}])
    with pytest.raises(ValueError, match="outside"):
        provider.analyze_video(video)


@pytest.mark.parametrize("patch", [
    {"hype": 11}, {"hype": float("nan")}, {"player_alive": "yes"},
    {"reaction": "unknown"}, {"caption": "two\nlines"}, {"extra": 1},
])
def test_assessment_strict_schema(patch):
    with pytest.raises(ValidationError):
        WindowAssessment.model_validate({**assessment(), **patch})


@pytest.mark.parametrize("patch", [{"end": 0}, {"start_seconds": 9}, {"type": "highlight"}])
def test_clip_schema(patch):
    with pytest.raises(ValidationError):
        ClipList.model_validate({"clips": [{**clip(), **patch}]})


def test_candidate_validation():
    with pytest.raises(ValidationError):
        ScoringCandidate.model_validate(candidate(3, 2))


@pytest.mark.parametrize("alive", [True, False, None])
def test_window_scoring_preserves_metadata_and_guards_spectators(video, alive):
    provider = MockProvider([{**assessment(), "player_alive": alive}])
    result = provider.score_windows(video, [candidate()])[0]
    assert result.start == 1 and result.end == 3 and result.score == 1.5
    assert result.signals == {"motion": 2.0}
    assert result.hype == (8 if alive else 0)
    assert result.kind == ("highlight" if alive else "neutral")
    assert not Path(provider.calls[0][0]).exists()


def test_invalid_candidate_batch_makes_no_calls(video):
    provider = MockProvider([])
    with pytest.raises(ValueError):
        provider.score_windows(video, [candidate(), candidate(5, 100)])
    assert provider.calls == []
    assert provider.score_windows("missing.mp4", []) == []


def test_retry_schema_and_transient_error(video, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("services.video_understanding.time.sleep", sleep)
    provider = MockProvider([TimeoutError(), "{}", {"clips": []}], ProviderConfig(backoff_seconds=0.25))
    assert provider._infer(video, "find clips", ClipList).clips == []
    assert [call.args[0] for call in sleep.call_args_list] == [0.25, 0.5]


def test_retry_exhaustion_and_permanent_error(video):
    provider = MockProvider(["{}"] * 3, config())
    with pytest.raises(ValidationError):
        provider.analyze_video(video)
    assert len(provider.calls) == 3
    provider = MockProvider([ValueError("bad input")], config())
    with pytest.raises(ValueError):
        provider.analyze_video(video)
    assert len(provider.calls) == 1


def test_file_cache_hash_and_delete(video, tmp_path):
    client = sdk_client()
    provider = GeminiProvider(client=client, config=config())
    duplicate = tmp_path / "duplicate.mp4"
    duplicate.write_bytes(video.read_bytes())
    first = provider._upload_file(video)
    assert provider._upload_file(duplicate) is first
    assert client.files.upload.call_count == 1
    provider.delete_file(first)
    provider._upload_file(video)
    assert client.files.upload.call_count == 2
    provider.close()
    assert not provider._cache


def test_file_cache_expiry_and_missing(video):
    client = sdk_client()
    provider = GeminiProvider(client=client, config=config())
    first = provider._upload_file(video)
    key = next(iter(provider._cache))
    provider._cache[key] = (first, -1)
    provider._upload_file(video)
    assert client.files.upload.call_count == 2
    client.files.get.side_effect = HTTPError("unused", 404, "missing", {}, None)
    provider._upload_file(video)
    assert client.files.upload.call_count == 3


def test_processing_failure_cleanup(video):
    client = sdk_client()
    client.files.upload.return_value.state.name = "FAILED"
    provider = GeminiProvider(client=client, config=config())
    with pytest.raises(RuntimeError):
        provider._upload_file(video)
    client.files.delete.assert_called_once()
    assert not provider._cache


def test_processing_timeout(video, monkeypatch):
    client = sdk_client()
    client.files.upload.return_value.state.name = "PROCESSING"
    monkeypatch.setattr("services.gemini_client.time.sleep", lambda _: None)
    provider = GeminiProvider(client=client, config=config(processing_timeout_seconds=0.001))
    with pytest.raises(TimeoutError):
        provider._upload_file(video)
    client.files.delete.assert_called_once()


def test_gemini_legacy_pipeline_config_and_logging(video, caplog):
    client = sdk_client([{"clips": [clip()]}, {"segments": [{"source_start": 0.5, "source_end": 1.5}]}])
    provider = GeminiVideoClient(client=client, config=config(input_usd_per_million=1, output_usd_per_million=2))
    with caplog.at_level(logging.INFO):
        clips = provider.find_clips(provider.upload_video(video), "Find clips")
        plan = provider.plan_edit("Plan an edit")
    assert clips[0]["start"] == 0.5 and plan["segments"][0]["source_end"] == 1.5
    call = client.models.generate_content.call_args_list[0].kwargs
    assert call["config"].response_schema is ClipList
    assert call["config"].media_resolution.value == "MEDIA_RESOLUTION_LOW"
    assert call["contents"][0].video_metadata.fps == 2
    assert "estimated_usd=0.00012" in caplog.text


def test_gemini_retries_http_and_schema(video):
    client = sdk_client([HTTPError("unused", 429, "rate limit", {}, None), {}, {"clips": []}])
    provider = GeminiProvider(client=client, config=config())
    assert provider.analyze_video(video).clips == []
    assert client.models.generate_content.call_count == 3
    assert client.files.upload.call_count == 1


def test_vertex_inline_and_limit(video):
    client = sdk_client([{"clips": []}])
    provider = GeminiProvider(client=client, vertexai=True, config=config())
    provider.analyze_video(video)
    client.files.upload.assert_not_called()
    part = client.models.generate_content.call_args.kwargs["contents"][0]
    assert part.inline_data.data == video.read_bytes()
    provider.inline_limit_bytes = 1
    with pytest.raises(ValueError, match="reduce chunk_seconds"):
        provider.analyze_video(video)


@pytest.mark.parametrize("vertex", [False, True])
def test_environment_auth_and_timeouts(monkeypatch, vertex):
    factory = Mock()
    monkeypatch.setattr("services.gemini_client.genai.Client", factory)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", str(vertex).lower())
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-vertex")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-studio")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    provider = GeminiProvider(config=config(timeout_seconds=12))
    assert provider.model == "gemini-3.5-flash-lite"
    args = factory.call_args.kwargs
    assert args["api_key"] == ("fake-vertex" if vertex else "fake-studio")
    assert args["vertexai"] is vertex
    assert args["http_options"].timeout == 12000
    assert args["http_options"].retry_options.attempts == 1


def test_local_frames_timestamps_schema_and_retry(video):
    payloads = []
    def transport(payload):
        payloads.append(payload)
        if len(payloads) == 1:
            raise TimeoutError()
        return {"choices": [{"message": {"content": json.dumps({"clips": [clip()]})}}]}
    provider = OpenAICompatibleVLMProvider("qwen", config=config(), max_frames=3, transport=transport)
    assert len(provider.analyze_video(video).clips) == 1
    assert len(payloads) == 2
    content = payloads[0]["messages"][0]["content"]
    assert [part["text"] for part in content[1::2]] == [
        "timestamp_seconds=0.000", "timestamp_seconds=2.000", "timestamp_seconds=4.000",
    ]
    assert all(p["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/") for p in content[2::2])
    assert payloads[0]["response_format"]["json_schema"]["strict"] is True


def test_actual_slice_duration_and_cleanup(video):
    with video_slice(video, 1.2, 3.2, 30) as window:
        assert abs(video_duration(window) - 2) < 0.3
    assert not window.exists()


def test_legacy_upload_analyze_plan_render(video, tmp_path):
    from services.ffmpeg_runner import FFmpegRunner
    client = sdk_client([
        {"clips": [clip()]},
        {"segments": [{"source_start": 0.5, "source_end": 1.5, "video_effects": ["none"]}]},
    ])
    provider = GeminiVideoClient(client=client, config=config())
    clips = provider.find_clips(provider.upload_video(video), "Find clips")
    plan = provider.plan_edit(json.dumps(clips))
    output = FFmpegRunner(tmp_path, video, 160, 120, 10).render(plan)
    assert output.is_file()
    assert 0.8 <= video_duration(output) <= 1.3


def test_agentic_unsupported_warns_once(video, caplog):
    client = sdk_client([{"clips": []}, {"clips": []}])
    client.interactions = None
    provider = GeminiProvider(client=client, agentic=True)
    with caplog.at_level(logging.WARNING):
        provider.analyze_video(video)
        provider.analyze_video(video)
    assert caplog.text.count("Agentic video processing is unavailable") == 1


def test_agentic_structured_request(video):
    client = sdk_client()
    client.interactions.create.return_value = SimpleNamespace(output_text='{"clips": []}', usage=None)
    provider = GeminiProvider(client=client, agentic=True)
    assert provider.analyze_video(video).clips == []
    request = client.interactions.create.call_args.kwargs
    assert request["input"][0]["processing"] == "agentic"
    assert request["input"][0]["resolution"] == "low"
    assert request["response_format"]["schema"] == ClipList.model_json_schema()
    assert request["timeout"] == 120
    client.models.generate_content.assert_not_called()


def test_vertex_agentic_falls_back_to_inline(video, caplog):
    client = sdk_client([{"clips": []}])
    provider = GeminiProvider(client=client, vertexai=True, agentic=True)
    with caplog.at_level(logging.WARNING):
        assert provider.analyze_video(video).clips == []
    assert "using standard sampling" in caplog.text
    client.interactions.create.assert_not_called()
    client.files.upload.assert_not_called()


def test_sdk_httpx_transport_retry(video):
    from httpx import ReadTimeout
    client = sdk_client([ReadTimeout("timeout"), {"clips": []}])
    assert GeminiProvider(client=client, config=config()).analyze_video(video).clips == []
    assert client.models.generate_content.call_count == 2


def test_local_http_payload_headers_and_timeout(monkeypatch):
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices": []}'
    transport = Mock(return_value=response)
    monkeypatch.setattr("services.local_vlm.urlopen", transport)
    provider = OpenAICompatibleVLMProvider("molmo", api_key="test-only", config=config(timeout_seconds=17))
    assert provider._post({"model": "molmo"}) == {"choices": []}
    request = transport.call_args.args[0]
    assert request.full_url == "http://localhost:8000/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-only"
    assert transport.call_args.kwargs["timeout"] == 17


def test_local_http_auth_failure_not_retried(video):
    transport = Mock(side_effect=HTTPError("unused", 401, "auth", {}, None))
    provider = OpenAICompatibleVLMProvider("qwen", config=config(), max_frames=1, transport=transport)
    with pytest.raises(HTTPError):
        provider.analyze_video(video)
    assert transport.call_count == 1


def test_cache_lru_eviction(video, tmp_path):
    client = sdk_client()
    provider = GeminiProvider(client=client, cache_size=1)
    provider._upload_file(video)
    second = tmp_path / "another.mp4"
    second.write_bytes(b"different content for mocked upload")
    client.files.upload.return_value = SimpleNamespace(
        name="files/second", uri="unused", mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE"))
    provider._upload_file(second)
    assert len(provider._cache) == 1
    client.files.delete.assert_called_once_with(name="files/example")
