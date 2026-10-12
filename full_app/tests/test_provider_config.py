from unittest.mock import Mock

import pytest

from pipeline import Pipeline
from services.provider_config import configuration


@pytest.mark.parametrize('vertex', [False, True])
@pytest.mark.parametrize('request_key', [None, 'request-test-key'])
def test_pipeline_credentials(monkeypatch, vertex, request_key):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_GENAI_USE_VERTEXAI', str(vertex).lower())
    monkeypatch.setenv('GOOGLE_API_KEY' if vertex else 'GEMINI_API_KEY', 'environment-test-key')
    factory = Mock()
    monkeypatch.setattr('services.gemini_client.genai.Client', factory)
    Pipeline().client({'options': {}}, request_key)
    assert factory.call_args.kwargs['api_key'] == (request_key or 'environment-test-key')
    assert factory.call_args.kwargs['vertexai'] is vertex
    assert configuration()['has_api_key'] is True
    assert 'environment-test-key' not in str(configuration())


def test_unknown_provider_never_constructs_paid_client(monkeypatch):
    factory = Mock()
    monkeypatch.setattr('services.gemini_client.genai.Client', factory)
    with pytest.raises(ValueError, match='Unknown provider'):
        Pipeline().client({'options': {'provider': 'typo'}}, None)
    factory.assert_not_called()


def test_local_planner_uses_vertex_selection(monkeypatch):
    from pipeline.providers import LocalClient
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_API_KEY', 'vertex-test')
    monkeypatch.setenv('GOOGLE_GENAI_USE_VERTEXAI', 'true')
    factory = Mock()
    monkeypatch.setattr('services.gemini_client.genai.Client', factory)
    monkeypatch.setattr('services.gemini_client.GeminiVideoClient.plan_edit', lambda *a: {'segments': []})
    LocalClient().plan_edit('test')
    assert factory.call_args.kwargs['vertexai'] is True
    assert factory.call_args.kwargs['api_key'] == 'vertex-test'
