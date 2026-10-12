import io
import json
import subprocess
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from server.api import create_app
from server.pipeline import Pipeline


@pytest.fixture(scope='session')
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp('media') / 'synthetic.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '3', '-c:v', 'libx264',
                    '-c:a', 'aac', '-shortest', str(path)], check=True)
    return path.read_bytes()


class FakePipeline:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail_plan = False

    def analyze(self, job, key):
        self.calls.append('analyze')
        self.entered.set()
        if self.block:
            assert self.release.wait(5)
        job['clips'] = [dict(id=str(i), start_seconds=i, end_seconds=i + 1, description='kill') for i in range(2)]

    def plan(self, job, key):
        self.calls.append('plan')
        if self.fail_plan:
            raise RuntimeError('secret-key-must-not-leak')
        job['edit_plan'] = {'segments': [dict(source_start=c['start_seconds'], source_end=c['end_seconds'])
                                         for c in job['clips'] if c.get('keep', True)]}

    def render(self, job, key):
        self.calls.append('render')
        path = Path(job['dir']) / 'output.mp4'
        path.write_bytes(Path(job['source']).read_bytes())
        job['output'] = str(path)


@pytest.fixture
def setup(tmp_path):
    pipeline = FakePipeline()
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path), 'SSE_INTERVAL': .001}, pipeline)
    yield app, app.test_client(), pipeline
    pipeline.release.set()
    app.extensions['job_queue'].close()


def upload(client, video, legacy=False):
    response = client.post('/api/upload' if legacy else '/api/jobs',
                           data={'video': (io.BytesIO(video), '../../evil.mp4')})
    assert response.status_code == (200 if legacy else 201)
    return response.json['job_id']


def wait(app, job_id):
    queue = app.extensions['job_queue']
    with queue.lock:
        future = queue.active.get(job_id)
    if future:
        future.result(timeout=60)
    return app.extensions['job_store'].get(job_id)


def test_lifecycle_and_legacy(setup, video):
    app, client, pipeline = setup
    job = upload(client, video, True)
    assert client.post('/api/analyze', json={'job_id': job, 'attitude': 'mean', 'splits': 1},
                       headers={'X-API-Key': 'secret-key-must-not-leak'}).json['clips']
    assert client.post('/api/plan', json={'job_id': job, 'edit_style': 'clean_edit'}).json['edit_plan']
    result = client.post('/api/render', json={'job_id': job, 'generate_thumbnails': False})
    assert result.status_code == 200
    assert client.get(result.json['download_url']).data == video
    assert client.get('/api/status/' + job).json['has_output']
    assert client.get('/api/stream/' + job).status_code == 200
    assert pipeline.calls == ['analyze', 'plan', 'render']
    assert 'secret-key-must-not-leak' not in (Path(app.config['WORKSPACE']) / 'jobs.sqlite3').read_bytes().decode(errors='ignore')
    assert 'secret-key-must-not-leak' not in client.get('/api/log/' + job).text
    assert 'source' not in client.get('/api/jobs/' + job).json


def test_async_edits_idempotency(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    url = '/api/jobs/' + job
    assert client.post(url + '/analyze', json={'mode': 'nice'}).status_code == 202
    assert wait(app, job)['status'] == 'planned'
    assert client.post(url + '/analyze', json={'mode': 'nice'}).status_code == 202
    wait(app, job)
    assert pipeline.calls == ['analyze', 'plan']
    edits = [dict(id='1', start_seconds=1.1, end_seconds=1.8, keep=True),
             dict(id='0', start_seconds=0, end_seconds=.9, keep=False)]
    assert client.patch(url + '/clips', json={'clips': edits}).json['plan'] is None
    assert client.post(url + '/render', json={'preset': 'vertical'}).status_code == 202
    result = wait(app, job)
    assert result['status'] == 'done'
    assert result['edit_plan']['segments'] == [{'source_start': 1.1, 'source_end': 1.8}]
    assert pipeline.calls == ['analyze', 'plan', 'plan', 'render']
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert not (Path(app.config['WORKSPACE']) / job).exists()


def test_cancel_busy_and_duplicate(setup, video):
    app, client, pipeline = setup
    pipeline.block = True
    job = upload(client, video)
    url = '/api/jobs/' + job
    assert client.post(url + '/analyze', json={'mode': 'mean'}).status_code == 202
    assert pipeline.entered.wait(2)
    assert client.post(url + '/analyze', json={'mode': 'mean'}).status_code == 202
    assert client.post(url + '/analyze', json={'mode': 'nice'}).status_code == 409
    assert client.patch(url + '/clips', json={'clips': []}).status_code == 409
    assert client.post(url + '/cancel').json['status'] == 'cancelled'
    assert client.delete(url).status_code == 409
    pipeline.release.set()
    assert wait(app, job)['status'] == 'cancelled'
    assert pipeline.calls == ['analyze']
    assert client.get(url + '/download').status_code == 404


def test_retry_failed_checkpoint_and_redaction(setup, video):
    app, client, pipeline = setup
    pipeline.fail_plan = True
    job = upload(client, video)
    url = '/api/jobs/' + job
    client.post(url + '/analyze', json={})
    result = wait(app, job)
    assert result['status'] == 'error'
    assert 'analyze' in result['completed']
    assert 'secret-key' not in json.dumps(client.get(url).json)
    pipeline.fail_plan = False
    client.post(url + '/analyze', json={})
    assert wait(app, job)['status'] == 'planned'
    assert pipeline.calls == ['analyze', 'plan', 'plan']


def test_restart_recovery_and_cancel_persistence(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    cancelled = upload(client, video)
    client.post('/api/jobs/' + cancelled + '/cancel')
    store = app.extensions['job_store']
    snapshot = store.get(job)
    pipeline.analyze(snapshot, None)
    snapshot.update(status='planning', target='render', completed=['upload', 'analyze'])
    store.save(snapshot)
    app.extensions['job_queue'].close()
    fresh_pipeline = FakePipeline()
    fresh = create_app({'TESTING': True, 'WORKSPACE': app.config['WORKSPACE']}, fresh_pipeline)
    try:
        assert wait(fresh, job)['status'] == 'done'
        assert fresh_pipeline.calls == ['plan', 'render']
        assert fresh.extensions['job_store'].get(cancelled)['status'] == 'cancelled'
    finally:
        fresh.extensions['job_queue'].close()


def test_sse_replay_and_heartbeat(setup, video):
    app, client, _ = setup
    job = upload(client, video)
    response = client.get('/api/jobs/' + job + '/events', buffered=False)
    assert response.mimetype == 'text/event-stream'
    first = next(response.response).decode()
    assert 'event: progress' in first and 'uploaded' in first
    seq = first.splitlines()[0].split(': ')[1]
    response.close()
    client.post('/api/jobs/' + job + '/cancel')
    response = client.get('/api/jobs/' + job + '/events', headers={'Last-Event-ID': seq}, buffered=False)
    assert 'cancelled' in next(response.response).decode()
    assert 'heartbeat' in next(response.response).decode()
    response.close()


@pytest.mark.parametrize('data', [[], None, {'mode': 'evil'}, {'style': []}, {'use_signals': 'true'},
                                  {'splits': 0}, {'splits': True}, {'max_duration': float('nan')},
                                  {'preset': 'huge'}, {'unknown': True}, {'provider': []}, {'window_scoring': 1}, {'sam_reframe': 'yes'}])
def test_bad_options(setup, video, data):
    _, client, _ = setup
    job = upload(client, video)
    assert client.post('/api/jobs/' + job + '/analyze', json=data).status_code in (400, 415)


def test_bad_upload_limits_and_missing(setup, video):
    app, client, _ = setup
    assert client.post('/api/jobs').status_code == 400
    assert client.post('/api/jobs', data={'video': (io.BytesIO(b'bad'), 'bad.mp4')}).status_code == 400
    assert not [p for p in Path(app.config['WORKSPACE']).iterdir() if p.is_dir()]
    app.config['MAX_CONTENT_LENGTH'] = 20
    assert client.post('/api/jobs', data={'video': (io.BytesIO(video), 'big.mp4')}).status_code == 413
    assert client.get('/api/jobs/missing').status_code == 404


def test_bad_edits_and_plan(setup, video):
    app, client, _ = setup
    job = upload(client, video)
    url = '/api/jobs/' + job
    client.post(url + '/analyze', json={})
    wait(app, job)
    for clips in ([dict(id='0', start_seconds=2, end_seconds=1)],
                  [dict(id='bad', start_seconds=0, end_seconds=1)],
                  [dict(id='0', start_seconds=0, end_seconds=99)],
                  [dict(id='0', start_seconds=0, end_seconds=1)] * 2):
        assert client.patch(url + '/clips', json={'clips': clips}).status_code == 400
    assert client.post(url + '/render', json={'edit_plan': {'segments': []}}).status_code == 400
    assert client.get(url + '/events', headers={'Last-Event-ID': 'bad'}).status_code == 400


@pytest.mark.parametrize('preset,dimensions', [('square', (1080, 1080)), ('vertical', (1080, 1920)),
                                               ('landscape', (1920, 1080))])
def test_default_pipeline_mocked_gemini_and_real_render(tmp_path, video, monkeypatch, preset, dimensions):
    client_mock = Mock()
    client_mock.score_windows.return_value = []
    client_mock.find_clips.return_value = [{'start': '0:00', 'end': '0:01', 'description': 'kill'}]
    client_mock.plan_edit.return_value = {'segments': [{'source_start': 0, 'source_end': 1,
                                                       'video_effects': [], 'sound_effects': []}]}
    monkeypatch.setattr('pipeline.orchestrator.GeminiVideoClient', Mock(return_value=client_mock))
    monkeypatch.setenv('GEMINI_API_KEY', 'fake')
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path)})
    client = app.test_client()
    try:
        job = upload(client, video)
        url = '/api/jobs/' + job
        assert client.post(url + '/analyze', json={'use_signals': True, 'reactions': True,
                                                  'captions': True, 'sam': True, 'provider': 'optional'}).status_code == 202
        assert wait(app, job)['status'] == 'planned'
        assert client.post(url + '/render', json={'preset': preset}).status_code == 202
        result = wait(app, job)
        assert result['status'] == 'done', result
        assert any('services.providers' in w for w in result['warnings'])
        assert 'render_v2' in result['timings']
        events = [json.loads(data) for _, data in app.extensions['job_store'].events(job, 0)]
        assert any(e.get('pipeline_stage') == 'rank_merge' for e in events)
        assert any('render_v2' in (e.get('timings') or {}) for e in events)
        from services.probe import probe_video
        metadata = probe_video(result['output'])
        assert (metadata['width'], metadata['height']) == dimensions
        assert not (Path(result['dir']) / 'render_tmp').exists()
        client_mock.find_clips.assert_called_once()
        client_mock.plan_edit.assert_called_once()
    finally:
        app.extensions['job_queue'].close()


def test_workspace_exclusive_and_crash_cleanup(setup, video):
    app, client, _ = setup
    with pytest.raises(RuntimeError, match='already has a job worker'):
        create_app({'WORKSPACE': app.config['WORKSPACE']}, FakePipeline())
    job = upload(client, video)
    workspace = Path(app.config['WORKSPACE'])
    orphan = workspace / ('f' * 32)
    orphan.mkdir()
    (orphan / 'upload.part').write_bytes(b'partial')
    scratch = workspace / job / 'render_tmp'
    scratch.mkdir()
    (scratch / 'partial.mp4').write_bytes(b'partial')
    app.extensions['job_queue'].close()
    fresh = create_app({'WORKSPACE': str(workspace)}, FakePipeline())
    try:
        assert not scratch.exists()
        assert not orphan.exists()
        assert fresh.test_client().get('/api/stream/' + job).data == video
    finally:
        fresh.extensions['job_queue'].close()


def test_changed_analysis_prompt_invalidates_checkpoints(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    url = '/api/jobs/' + job
    client.post(url + '/analyze', json={'prompt': 'first'})
    wait(app, job)
    client.post(url + '/analyze', json={'prompt': 'second'})
    wait(app, job)
    assert pipeline.calls == ['analyze', 'plan', 'analyze', 'plan']


def test_scoring_and_render_flags_invalidate_correct_stages(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    url = '/api/jobs/' + job
    client.post(url + '/render', json={})
    assert wait(app, job)['status'] == 'done'
    client.post(url + '/render', json={'sam_reframe': True})
    assert wait(app, job)['status'] == 'done'
    assert pipeline.calls == ['analyze', 'plan', 'render', 'render']
    client.post(url + '/render', json={'window_scoring': False})
    assert wait(app, job)['status'] == 'done'
    assert pipeline.calls[-3:] == ['analyze', 'plan', 'render']


def test_custom_plan_skips_provider_and_queue_capacity(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    plan = {'segments': [{'source_start': 0, 'source_end': 1}]}
    assert client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan}).status_code == 202
    assert wait(app, job)['status'] == 'done'
    assert pipeline.calls == ['render']
    assert client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan}).status_code == 202
    assert wait(app, job)['status'] == 'done'
    assert pipeline.calls == ['render']
    client.post('/api/jobs/' + job + '/analyze', json={})
    assert wait(app, job)['clips']
    assert pipeline.calls == ['render', 'analyze', 'plan']
    pipeline.entered.clear()
    pipeline.block = True
    app.extensions['job_queue'].capacity = 1
    job1, job2 = upload(client, video), upload(client, video)
    client.post('/api/jobs/' + job1 + '/analyze', json={})
    assert pipeline.entered.wait(2)
    assert client.post('/api/jobs/' + job2 + '/analyze', json={}).status_code == 409
    pipeline.release.set()
    wait(app, job1)
