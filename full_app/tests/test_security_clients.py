import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from capture.client import UploadClient
from discord_bot.core import Config, MontageService, Options, Source, select_source
from server.security import create_secure_app


def test_client_rejects_response_path_traversal(tmp_path):
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'test')
    client = UploadClient('http://localhost', transport=httpx.MockTransport(
        lambda _: httpx.Response(201, json={'id': '../secrets'})))
    try:
        with pytest.raises(ValueError):
            client.upload(video)
        with pytest.raises(ValueError):
            client.analyze('../secrets', {})
    finally:
        client.close()


def test_authenticated_upload_analyze_plan_render_download(video, tmp_path, monkeypatch):
    """Real protected HTTP routes and job queue; paid/render providers mocked."""
    token = 'test-only-' + 'a' * 32
    monkeypatch.setenv('LIM_API_TOKEN', token)
    calls = []
    def analyze(job, key):
        calls.append('analyze')
        job['clips'] = [{'id': '0', 'start_seconds': 0, 'end_seconds': 1}]
    def plan(job, key):
        calls.append('plan')
        job['edit_plan'] = {'segments': [{'source_start': 0, 'source_end': 1}]}
    def render(job, key):
        calls.append('render')
        job['output'] = str(Path(job['dir']) / 'output.mp4')
        Path(job['output']).write_bytes(video.read_bytes())
    app = create_secure_app({'TESTING': True, 'WORKSPACE': str(tmp_path / 'workspace')},
                            SimpleNamespace(analyze=analyze, plan=plan, render=render))
    flask = app.test_client()
    headers = {'Authorization': 'Bearer ' + token}
    def send(request):
        assert request.headers['Authorization'] == headers['Authorization']
        response = flask.open(request.url.path, method=request.method, data=request.content,
                              headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.data)
    client = UploadClient('http://localhost', transport=httpx.MockTransport(send))
    queue = app.extensions['job_queue']
    def wait(job):
        with queue.lock:
            future = queue.active.get(job)
        if future:
            future.result(timeout=10)
    try:
        assert flask.post('/api/jobs').status_code == 401
        job = client.upload(video)
        client.analyze(job, {})
        wait(job)
        assert flask.post(f'/api/jobs/{job}/render', json={}, headers=headers).status_code == 202
        wait(job)
        assert calls == ['analyze', 'plan', 'render']
        assert flask.get(f'/api/jobs/{job}/download').status_code == 401
        response = flask.get(f'/api/jobs/{job}/download', headers=headers)
        try:
            assert response.status_code == 200 and response.data == video.read_bytes()
        finally:
            response.close()
    finally:
        client.close()
        queue.close()


def test_discord_filename_and_global_capacity():
    config = Config('test-token', frozenset({1}))
    attachment = SimpleNamespace(filename='C:\\private\\game.mp4', size=1,
                                 url='https://cdn.discordapp.com/a')
    assert select_source(config, attachment).filename == 'game.mp4'
    api = SimpleNamespace(upload=AsyncMock())
    service = MontageService(replace(config, max_active=1), api)
    service.active.add(99)
    sink = SimpleNamespace(send_status=AsyncMock())
    asyncio.run(service.run(2, 1, Source('unused', 'game.mp4'), Options(), sink))
    api.upload.assert_not_awaited()
    assert 'busy' in sink.send_status.await_args.args[0]


def test_discord_oversize_and_exception_remove_partial_files(tmp_path):
    pytest.importorskip('aiohttp')
    from discord_bot.api import JobAPI
    api = JobAPI(Config('test-token', frozenset({1})))
    class Response:
        status, content_length, headers = 200, None, {}
        async def __aenter__(self):
            self.content = self
            return self
        async def __aexit__(self, *args):
            pass
        async def iter_chunked(self, size):
            yield b'123'
            yield b'456'
    session = SimpleNamespace(get=Mock(return_value=Response()))
    target = tmp_path / 'partial.mp4'
    assert not asyncio.run(api.transfer(session, 'https://example.test/a', target, 4))
    assert not target.exists()


def test_discord_token_sent_only_to_api(monkeypatch):
    aiohttp = pytest.importorskip('aiohttp')
    from discord_bot.api import JobAPI
    monkeypatch.setenv('LIM_API_TOKEN', 'test-only-' + 'a' * 32)
    sessions = []
    def session(**kwargs):
        sessions.append(kwargs)
        return SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(aiohttp, 'ClientSession', session)
    # Avoid allocating real connectors; no gateway or Internet traffic.
    monkeypatch.setattr(aiohttp, 'TCPConnector', Mock())
    import discord_bot.api as adapter
    monkeypatch.setattr(adapter, 'PublicResolver', Mock())
    api = JobAPI(Config('test-token', frozenset({1})))
    async def run():
        await api.open()
        await api.close()
    asyncio.run(run())
    assert sessions[0]['headers']['Authorization'].startswith('Bearer ')
    assert 'Authorization' not in sessions[1]['headers']
    assert sessions[1]['auto_decompress'] is False


def test_capture_state_does_not_follow_predictable_temp_symlink(tmp_path):
    from capture.watcher import FolderWatcher
    folder = tmp_path / 'recordings'
    folder.mkdir()
    state = tmp_path / 'state.json'
    victim = tmp_path / 'victim'
    victim.write_text('untouched')
    (tmp_path / 'state.json.tmp').symlink_to(victim)
    watcher = FolderWatcher(folder, Mock(), {}, state)
    watcher.persist()
    assert state.read_text() == '{}'
    assert victim.read_text() == 'untouched'
