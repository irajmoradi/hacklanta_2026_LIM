import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from capture.__main__ import main
from capture.client import UploadClient
from capture.obs import OBSClient, OBSError, digest, trigger_replay
from capture.watcher import FolderWatcher, start_observer


@pytest.fixture
def watch(tmp_path):
    folder = tmp_path / 'recordings'
    folder.mkdir()
    now = [0.0]
    client = Mock()
    client.upload.return_value = 'job-1'
    watcher = FolderWatcher(folder, client, {'mode': 'mean'}, tmp_path / 'state.json',
                            clock=lambda: now[0], stable_seconds=3, retry_seconds=5)
    return watcher, client, now, folder


def settle(watcher, now):
    watcher.scan()
    now[0] += 3
    watcher.scan()


def test_growth_and_same_size_rewrite_reset_quiet_window(watch):
    watcher, client, now, folder = watch
    path = folder / 'replay.mp4'
    path.write_bytes(b'first')
    watcher.scan()
    now[0] = 2
    path.write_bytes(b'longer clip')
    watcher.scan()
    now[0] = 4
    watcher.scan()
    client.upload.assert_not_called()
    stamp = path.stat().st_mtime_ns
    os.utime(path, ns=(stamp + 100, stamp + 100))
    watcher.scan()
    now[0] = 6
    watcher.scan()
    client.upload.assert_not_called()
    now[0] = 7
    watcher.scan()
    client.upload.assert_called_once_with(path)
    client.analyze.assert_called_once_with('job-1', {'mode': 'mean'})
    watcher.scan()
    client.upload.assert_called_once()


def test_empty_temporary_deleted_nested_and_renamed_files(watch):
    watcher, client, now, folder = watch
    (folder / 'empty.mp4').touch()
    temporary = folder / 'clip.mp4.part'
    temporary.write_bytes(b'data')
    settle(watcher, now)
    client.upload.assert_not_called()
    nested = folder / 'game'
    nested.mkdir()
    final = nested / 'replay.MKV'
    temporary.rename(final)
    watcher.scan()
    client.upload.assert_not_called()
    now[0] += 3
    watcher.scan()
    client.upload.assert_called_once_with(final)
    other = folder / 'deleted.mp4'
    other.write_bytes(b'data')
    watcher.scan()
    other.unlink()
    settle(watcher, now)
    client.upload.assert_called_once()


def test_startup_baseline_and_restart_dedup(watch):
    watcher, client, now, folder = watch
    old = folder / 'old.mp4'
    old.write_bytes(b'old')
    restarted = FolderWatcher(folder, client, {}, watcher.state, clock=lambda: now[0], stable_seconds=3)
    settle(restarted, now)
    client.upload.assert_not_called()
    old.write_bytes(b'new version')
    settle(restarted, now)
    client.upload.assert_called_once()
    again = FolderWatcher(folder, client, {}, watcher.state, include_existing=True,
                          clock=lambda: now[0], stable_seconds=3)
    settle(again, now)
    client.upload.assert_called_once()


def test_retry_analysis_after_restart_keeps_job(watch):
    watcher, client, now, folder = watch
    (folder / 'replay.mp4').write_bytes(b'data')
    client.analyze.side_effect = RuntimeError('offline')
    settle(watcher, now)
    watcher.scan()
    client.analyze.assert_called_once()
    client.analyze.side_effect = None
    restarted = FolderWatcher(folder, client, {}, watcher.state, clock=lambda: now[0], stable_seconds=3)
    settle(restarted, now)
    client.upload.assert_called_once()
    assert client.analyze.call_count == 2
    assert next(iter(json.loads(watcher.state.read_text()).values()))['done']


def test_upload_failure_retries_without_blocking_other_files(watch):
    watcher, client, now, folder = watch
    for name in ('a.mp4', 'b.mp4'):
        (folder / name).write_bytes(b'data')
    client.upload.side_effect = [OSError('offline'), 'job-2', 'job-3']
    settle(watcher, now)
    assert client.upload.call_count == 2
    assert client.analyze.call_count == 1
    now[0] += 5
    watcher.scan()
    assert client.upload.call_count == 3
    assert client.analyze.call_count == 2


def test_mutation_during_upload_never_starts_analysis(watch):
    watcher, client, now, folder = watch
    path = folder / 'replay.mp4'
    path.write_bytes(b'data')
    def upload(path):
        path.write_bytes(b'more data')
        return 'job-1'
    client.upload.side_effect = upload
    settle(watcher, now)
    client.analyze.assert_not_called()


def test_streaming_api_contract_and_errors(tmp_path):
    path = tmp_path / 'replay.mp4'
    path.write_bytes(b'synthetic payload')
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == '/api/jobs':
            assert b'name="video"' in request.content
            assert b'synthetic payload' in request.content
            return httpx.Response(201, json={'id': 'abc'})
        assert request.url.path == '/api/jobs/abc/analyze'
        assert json.loads(request.content) == {'mode': 'nice'}
        return httpx.Response(202, json={})
    client = UploadClient('http://localhost:8000', transport=httpx.MockTransport(respond))
    client.analyze(client.upload(path), {'mode': 'nice'})
    assert len(requests) == 2
    client.close()
    client = UploadClient('http://localhost', transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        client.upload(path)
    client.close()


class Socket:
    def __init__(self, responses=None, auth=None, failed=None):
        self.messages = [{'op': 0, 'd': {'rpcVersion': 1, **({'authentication': auth} if auth else {})}}]
        self.sent, self.responses = [], responses or {}
        self.failed = failed
        self.closed = False

    def send(self, value):
        packet = json.loads(value)
        self.sent.append(packet)
        if packet['op'] == 1:
            self.messages.append({'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        else:
            data = packet['d']
            self.messages.extend([{'op': 5, 'd': {'eventType': 'ReplayBufferSaved'}},
                                  {'op': 7, 'd': {'requestId': 'unrelated'}},
                                  {'op': 7, 'd': {'requestId': data['requestId'],
                                   'requestStatus': {'result': data['requestType'] != self.failed, 'code': 500},
                                   'responseData': self.responses.get(data['requestType'], {})}}])

    def recv(self):
        return json.dumps(self.messages.pop(0))

    def settimeout(self, value):
        assert value > 0

    def close(self):
        self.closed = True


def test_obs_auth_replay_and_request_shapes(monkeypatch):
    monkeypatch.setenv('OBS_WEBSOCKET_PASSWORD', 'test-password')
    socket = Socket({'GetReplayBufferStatus': {'outputActive': True}}, {'salt': 'salt', 'challenge': 'challenge'})
    with OBSClient(connector=lambda *a, **kw: socket) as obs:
        obs.save_replay()
    assert socket.closed
    assert socket.sent[0] == {'op': 1, 'd': {'rpcVersion': 1, 'eventSubscriptions': 0,
                            'authentication': digest(digest('test-passwordsalt') + 'challenge')}}
    assert [p['d']['requestType'] for p in socket.sent[1:]] == ['GetReplayBufferStatus', 'SaveReplayBuffer']
    assert all(p['op'] == 6 and p['d']['requestData'] == {} for p in socket.sent[1:])


@pytest.mark.parametrize('failed', [None, 'SaveReplayBuffer'])
def test_obs_inactive_and_error_responses(failed):
    socket = Socket({'GetReplayBufferStatus': {'outputActive': bool(failed)}}, failed=failed)
    with OBSClient(connector=lambda *a, **kw: socket) as obs:
        with pytest.raises(OBSError):
            obs.save_replay()
    assert socket.closed


def test_obs_missing_password_closes_socket(monkeypatch):
    monkeypatch.delenv('OBS_WEBSOCKET_PASSWORD', raising=False)
    socket = Socket(auth={'salt': 's', 'challenge': 'c'})
    with pytest.raises(OBSError):
        with OBSClient(connector=lambda *a, **kw: socket):
            pass
    assert socket.closed


def test_obs_context_shapes_and_event_hook():
    socket = Socket({'GetCurrentProgramScene': {'currentProgramSceneName': 'Gameplay'},
                     'GetSceneItemList': {'sceneItems': [
                         {'sourceName': 'Game', 'inputKind': 'game_capture', 'sceneItemEnabled': True},
                         {'sourceName': 'Hidden', 'inputKind': 'window_capture', 'sceneItemEnabled': False}]},
                     'GetInputSettings': {'inputSettings': {'window': 'Game.exe', 'capture_mode': 'window'}}})
    with OBSClient(connector=lambda *a, **kw: socket) as obs:
        assert obs.context() == {'scene': 'Gameplay', 'captures': [
            {'source': 'Game', 'kind': 'game_capture', 'window': 'Game.exe', 'capture_mode': 'window'}]}
    assert socket.sent[2]['d']['requestData'] == {'sceneName': 'Gameplay'}
    assert socket.sent[3]['d']['requestData'] == {'inputName': 'Game'}
    factory = MagicMock()
    assert trigger_replay({}, 'kill', factory) == {'saved': True, 'reason': 'kill'}
    factory.return_value.__enter__.return_value.save_replay.assert_called_once()


@pytest.mark.parametrize('config', [{'stable_seconds': 0}, {'poll_seconds': float('nan')},
                                  {'options': {'api_key': 'forbidden'}}, {'options': {'splits': 7}},
                                  {'obs': {'password': 'forbidden'}}, {'api': 'file:///tmp'},
                                  {'unknown': True}])
def test_cli_rejects_invalid_config(tmp_path, config):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    assert main(['--config', str(path), '--watch', str(tmp_path)]) == 2


def test_cli_overrides_and_event(monkeypatch, tmp_path):
    import capture.__main__ as cli
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'watch': 'missing', 'options': {'mode': 'mean'}}))
    run = Mock()
    monkeypatch.setattr(cli, 'run', run)
    assert main(['--config', str(path), '--watch', str(tmp_path), '--api', 'http://localhost:9000']) == 0
    config = run.call_args.args[0]
    assert config['watch'] == str(tmp_path.resolve())
    assert config['api'] == 'http://localhost:9000'
    assert config['options'] == {'mode': 'mean'}
    trigger = Mock(return_value={'saved': True})
    monkeypatch.setattr(cli, 'trigger_replay', trigger)
    assert main(['--event', 'round_win']) == 0
    trigger.assert_called_once_with({}, 'round_win')


def test_real_watchdog_wakeup(tmp_path):
    import threading
    pytest.importorskip('watchdog')
    wake = threading.Event()
    observer = start_observer(tmp_path, wake)
    try:
        (tmp_path / 'new.mp4').write_bytes(b'data')
        assert wake.wait(3)
    finally:
        observer.stop()
        observer.join(3)


def test_synthetic_video_flows_through_real_api(tmp_path, video):
    from server.api import create_app
    pipeline = Mock(spec=['analyze', 'plan', 'render'])
    def analyze(job, key):
        job['clips'] = [{'id': '1', 'start_seconds': 0, 'end_seconds': 1}]
    def plan(job, key):
        job['edit_plan'] = {'segments': [{'source_start': 0, 'source_end': 1}]}
    pipeline.analyze.side_effect = analyze
    pipeline.plan.side_effect = plan
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path / 'jobs')}, pipeline)
    flask = app.test_client()
    def transport(request):
        response = flask.open(request.url.path, method=request.method,
                              data=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.data)
    client = UploadClient('http://localhost:8000', transport=httpx.MockTransport(transport))
    now = [0]
    watcher = FolderWatcher(video.parent, client, {'mode': 'mean'}, tmp_path / 'state.json',
                            include_existing=True, clock=lambda: now[0], stable_seconds=3)
    try:
        settle(watcher, now)
        job = watcher.records[str(video)]['job']
        queue = app.extensions['job_queue']
        with queue.lock:
            future = queue.active.get(job)
        if future:
            future.result(timeout=10)
        result = app.extensions['job_store'].get(job)
        assert result['status'] == 'planned'
        assert result['options']['mode'] == 'mean'
        pipeline.analyze.assert_called_once()
        pipeline.plan.assert_called_once()
    finally:
        client.close()
        app.extensions['job_queue'].close()


def test_locked_file_waits_then_retries(watch, monkeypatch):
    watcher, client, now, folder = watch
    path = folder / 'locked.mp4'
    path.write_bytes(b'data')
    original = Path.open
    def locked(self, *args, **kwargs):
        if self == path:
            raise PermissionError('recording still open')
        return original(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', locked)
        settle(watcher, now)
    client.upload.assert_not_called()
    now[0] += 5
    watcher.scan()
    client.upload.assert_called_once_with(path)


def test_optional_dependencies_fall_back(monkeypatch, tmp_path):
    import builtins
    import threading
    from capture.__main__ import start_hotkey
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name.startswith(('watchdog', 'pynput')):
            raise ImportError(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    assert start_observer(tmp_path, threading.Event()) is None
    assert start_hotkey('<ctrl>+r', Mock()) is None


def test_shutdown_stops_workers_and_closes_http(monkeypatch, tmp_path):
    import signal
    import capture.__main__ as cli
    signals = {}
    previous = Mock()
    def register(sig, callback):
        signals[sig] = callback
        return previous
    monkeypatch.setattr(cli.signal, 'signal', register)
    watcher = Mock()
    watcher.scan.side_effect = lambda: signals[signal.SIGTERM]()
    monkeypatch.setattr(cli, 'FolderWatcher', Mock(return_value=watcher))
    client, observer, listener = Mock(), Mock(), Mock()
    monkeypatch.setattr(cli, 'UploadClient', Mock(return_value=client))
    monkeypatch.setattr(cli, 'start_observer', Mock(return_value=observer))
    def hotkey(combination, callback):
        callback()
        return listener
    monkeypatch.setattr(cli, 'start_hotkey', hotkey)
    replay = Mock()
    monkeypatch.setattr(cli, 'trigger_replay', replay)
    cli.run({'watch': str(tmp_path), 'api': 'http://localhost', 'options': {},
             'state': str(tmp_path / 'state.json'), 'stable_seconds': 3,
             'retry_seconds': 5, 'include_existing': False, 'poll_seconds': .001,
             'hotkey': '<ctrl>+r', 'obs': {}})
    replay.assert_called_once_with({})
    for worker in (observer, listener):
        worker.stop.assert_called_once()
        worker.join.assert_called_once()
    client.close.assert_called_once()
    assert all(handler is previous for handler in signals.values())


def test_obs_nested_scene_and_group_context():
    obs = OBSClient()
    def request(kind, data=None):
        if kind == 'GetCurrentProgramScene':
            return {'currentProgramSceneName': 'Root'}
        if kind == 'GetInputSettings':
            return {'inputSettings': {'window': 'Game.exe'}}
        name = data['sceneName']
        if name == 'Root':
            return {'sceneItems': [{'sourceName': 'Nested', 'sourceType': 'OBS_SOURCE_TYPE_SCENE'}]}
        if name == 'Nested':
            return {'sceneItems': [{'sourceName': 'Group', 'isGroup': True}]}
        assert kind == 'GetGroupSceneItemList'
        return {'sceneItems': [{'sourceName': 'Game', 'inputKind': 'game_capture'},
                              {'sourceName': 'Root', 'sourceType': 'OBS_SOURCE_TYPE_SCENE'}]}
    obs.request = Mock(side_effect=request)
    assert obs.context()['captures'][0]['window'] == 'Game.exe'
    assert obs.request.call_count == 5


def test_one_shot_connection_errors_are_clean(monkeypatch, caplog):
    import capture.__main__ as cli
    class LibraryConnectionError(Exception):
        pass
    monkeypatch.setattr(cli, 'trigger_replay', Mock(side_effect=LibraryConnectionError('private-response')))
    assert main(['--save-replay']) == 2
    assert 'private-response' not in caplog.text
