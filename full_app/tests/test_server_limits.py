"""FIX-1 regressions: no external providers; tiny synthetic media only."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from server.api import create_app
from server.resources import bounded_process, Resources
from server.validation import plan_valid
from test_jobs import FakePipeline, video, setup, upload, wait


def test_owner_checks_cover_every_alias_and_media(video, tmp_path):
    tokens = {'alice': 'a' * 32, 'bob': 'b' * 32}
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path), 'API_TOKENS': tokens}, FakePipeline())
    client = app.test_client()
    alice = {'Authorization': 'Bearer ' + tokens['alice']}
    bob = {'Authorization': 'Bearer ' + tokens['bob']}
    try:
        assert client.post('/api/jobs', headers={'X-API-Key': tokens['alice']}).status_code == 401
        response = client.post('/api/jobs', headers=alice, data={'video': (io.BytesIO(video), 'a.mp4')})
        assert response.status_code == 201
        job = response.json['id']
        assert '_owner' not in response.json
        root = '/api/jobs/' + job
        routes = [('GET', p) for p in (root, root + '/events', root + '/download', root + '/share/x',
                   '/api/status/' + job, '/api/download/' + job, '/api/stream/' + job, '/api/log/' + job)]
        routes += [('POST', root + '/' + action) for action in ('analyze', 'plan', 'render', 'cancel')]
        routes += [('PATCH', root + '/clips'), ('DELETE', root)]
        routes += [('POST', '/api/' + action) for action in ('analyze', 'plan', 'render')]
        for method, path in routes:
            assert client.open(path, method=method, headers=bob, json={'job_id': job}).status_code == 404, path
            assert client.open(path, method=method, json={'job_id': job}).status_code == 401, path
        assert client.get(root, headers=alice).status_code == 200
        assert client.get('/api/stream/' + job, headers=alice).data == video
        assert client.get('/api/health').status_code == 200
        assert client.delete(root, headers=alice).status_code == 204
    finally:
        app.extensions['job_queue'].close()


def test_unconfigured_remote_peer_fails_closed(setup):
    _, client, _ = setup
    assert client.get('/api/info', environ_base={'REMOTE_ADDR': '192.0.2.1'},
                      headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 401
    assert client.get('/api/info').status_code == 200


def test_stream_capacity_lifetime_and_idle_close(setup, video):
    app, client, _ = setup
    job = upload(client, video)
    url = '/api/jobs/' + job
    # Uploaded/terminal streams drain and return without waiting forever.
    assert client.get(url + '/events').data.count(b'event: progress') == 1
    store = app.extensions['job_store']
    current = store.get(job)
    current['status'] = 'rendering'
    store.save(current)
    app.config['SSE_MAX_SECONDS'] = .05
    responses = [client.get(url + '/events', buffered=False) for _ in range(8)]
    try:
        assert all(r.status_code == 200 for r in responses)
        assert client.get(url + '/events').status_code == 429
        started = time.monotonic()
        assert client.get('/api/health').status_code == 200
        assert client.get(url).status_code == 200
        assert time.monotonic() - started < 1
        assert b'heartbeat' in responses[0].data
    finally:
        for response in responses:
            response.close()
    assert client.get(url + '/events').status_code == 200


@pytest.mark.parametrize('change', [
    {'render_version': 3}, {'extra': 1}, {'music': {'path': '/etc/passwd'}},
    {'segments': [{'source_start': 0, 'source_end': 1, 'video_effects': ['bogus']}]},
    {'segments': [{'source_start': 0, 'source_end': 1, 'sound_effects': [{'sfx_key': 'bogus'}]}]},
    {'segments': [{'source_start': 0, 'source_end': 1, 'sound_effects': [{'sfx_key': 'none', 'offset_in_segment': '0'}]}]},
    {'segments': [{'source_start': 0, 'source_end': 1, 'fx': [{'name': 'bogus'}]}]},
    {'segments': [{'source_start': 0, 'source_end': 1, 'words': [{'start': 0, 'end': 2, 'text': 'late'}]}]},
    {'segments': [{'source_start': 0, 'source_end': 1}] * 101},
])
def test_bad_plan_rejected_without_mutation(setup, video, change):
    app, client, pipeline = setup
    job = upload(client, video)
    before = app.extensions['job_store'].get(job)
    plan = {'render_version': 2, 'segments': [{'source_start': 0, 'source_end': 1}], **change}
    response = client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan})
    assert response.status_code == 400, response.json
    assert app.extensions['job_store'].get(job) == before
    assert not pipeline.calls


def test_duration_accounts_for_speed_effects_cards_and_overlap():
    legacy = {'segments': [{'source_start': 0, 'source_end': 2, 'speed': .5, 'video_effects': ['slow_motion']}]}
    assert plan_valid(legacy, 3, 8) == legacy
    with pytest.raises(ValueError, match='max_duration'):
        plan_valid(legacy, 3, 7.9)
    v2 = {'render_version': 2, 'segments': [{'source_start': 0, 'source_end': 2}],
          'intro': {'text': 'Hello', 'duration': 1}, 'transition': 'flash', 'transition_duration': .2}
    assert plan_valid(v2, 3, 2.8) == v2
    with pytest.raises(ValueError, match='max_duration'):
        plan_valid(v2, 3, 2.7)


@pytest.mark.parametrize('version', [1, 2])
def test_current_review_ui_caption_alias_reaches_renderer(setup, video, version):
    app, client, _ = setup
    job = upload(client, video)
    plan = {'render_version': version, 'segments': [{'source_start': 0, 'source_end': 1,
                                                    'caption': 'Reviewed title'}]}
    assert client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan}).status_code == 202
    result = wait(app, job)
    assert result['status'] == 'done'
    assert result['edit_plan']['segments'][0]['title'] == 'Reviewed title'
    assert 'caption' not in result['edit_plan']['segments'][0]


def test_generated_plan_cap_prevents_render(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    assert client.post('/api/jobs/' + job + '/render', json={'max_duration': 1}).status_code == 202
    assert wait(app, job)['status'] == 'error'
    assert pipeline.calls == ['analyze', 'plan']


def test_upload_quota_media_limits_and_reservation_release(setup, video):
    app, client, _ = setup
    app.config['OWNER_BYTES'] = 1
    assert client.post('/api/jobs', data={'video': (io.BytesIO(video), 'a.mp4')}).status_code == 400
    assert not app.extensions['job_store'].all()
    app.config['OWNER_BYTES'] = 1024**3
    app.config['MAX_MEDIA_DURATION'] = 1
    assert client.post('/api/jobs', data={'video': (io.BytesIO(video), 'a.mp4')}).status_code == 400
    assert not list(Path(app.config['WORKSPACE']).glob('*/source.mp4'))
    app.config['MAX_MEDIA_DURATION'] = 10
    upload(client, video)


def test_concurrent_upload_reservations_and_retention(setup, video):
    app, client, _ = setup
    job = upload(client, video)
    store, queue = app.extensions['job_store'], app.extensions['job_queue']
    resources = Resources(Path(app.config['WORKSPACE']), store, app.config)
    app.config['OWNER_BYTES'] = 100000
    with resources.upload('other', 60000):
        with pytest.raises(ValueError, match='quota'):
            with resources.upload('other', 60000):
                pass
    with resources.upload('other', 60000):
        pass
    app.config['JOB_TTL_SECONDS'] = -1
    queue.active[job] = None
    resources.reap(queue)
    assert store.get(job)
    queue.active.pop(job)
    resources.reap(queue)
    with pytest.raises(KeyError):
        store.get(job)
    assert not (Path(app.config['WORKSPACE']) / job).exists()
    assert not store.events(job, 0)


@pytest.mark.skipif(os.name != 'posix', reason='Linux process-group contract')
@pytest.mark.parametrize('cancel', [False, True])
def test_hung_process_and_descendant_are_killed(tmp_path, cancel):
    pidfile = tmp_path / 'pid'
    command = [sys.executable, '-c',
               "import subprocess,time,pathlib,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)", str(pidfile)]
    with pytest.raises((TimeoutError, RuntimeError)):
        bounded_process(command, b'', timeout=.6,
                        cancelled=lambda: cancel and pidfile.exists())
    pid = int(pidfile.read_text())
    # A killed orphan may briefly remain a zombie until PID 1 reaps it.
    stat = Path('/proc') / str(pid) / 'stat'
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            if stat.read_text().split()[2] == 'Z':
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        time.sleep(.01)
    else:
        pytest.fail('Descendant survived process-group termination')


@pytest.mark.skipif(os.name != 'posix', reason='Linux resource limit contract')
def test_worker_enforces_memory_and_inherits_limits_to_children():
    script = '''
import io, json, resource, subprocess, sys, types
from server.stage_worker import main
def probe(path):
    try:
        bytearray(128 * 1024**2)
        limited = False
    except MemoryError:
        limited = True
    child = subprocess.check_output([sys.executable, '-c',
        'import json,resource; print(json.dumps([resource.getrlimit(resource.RLIMIT_AS), resource.getrlimit(resource.RLIMIT_FSIZE)]))'])
    return dict(limited=limited, child=json.loads(child))
sys.modules['server.media'] = types.SimpleNamespace(probe_upload=probe)
sys.stdin = io.StringIO(json.dumps(dict(path='unused', memory=64*1024**2, file_bytes=65536)))
main()
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'limited': True, 'child': [[64 * 1024**2] * 2, [65536] * 2]}


def test_isolated_default_pipeline_renders_without_provider(tmp_path, video):
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path), 'STAGE_TIMEOUT_SECONDS': 60, 'ISOLATE_STAGES': True})
    try:
        client = app.test_client()
        job = upload(client, video)
        plan = {'render_version': 2, 'resolution': 720, 'segments': [{'source_start': 0, 'source_end': 1}]}
        assert client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan}).status_code == 202
        result = wait(app, job)
        assert result['status'] == 'done', result['error']
        assert Path(result['output']).stat().st_size > 0
    finally:
        app.extensions['job_queue'].close()


def test_isolated_stage_deadline_cleans_output_and_scratch(tmp_path, video):
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path),
                      'STAGE_TIMEOUT_SECONDS': .001, 'ISOLATE_STAGES': True})
    try:
        client = app.test_client()
        job = upload(client, video)
        plan = {'render_version': 2, 'segments': [{'source_start': 0, 'source_end': 1}]}
        assert client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan}).status_code == 202
        result = wait(app, job)
        assert result['status'] == 'error'
        assert 'TimeoutError' in result['error']
        assert not list((tmp_path / job).glob('*tmp'))
        assert not (tmp_path / job / 'output.mp4').exists()
        assert not list((tmp_path / job).glob('.stage-progress*'))
        assert client.get('/api/health').status_code == 200
    finally:
        app.extensions['job_queue'].close()


def test_http_cancel_interrupts_isolated_render(tmp_path, video):
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path),
                      'STAGE_TIMEOUT_SECONDS': 60, 'ISOLATE_STAGES': True})
    try:
        client = app.test_client()
        job = upload(client, video)
        plan = {'render_version': 2, 'segments': [{'source_start': 0, 'source_end': 2}] * 10}
        assert client.post('/api/jobs/' + job + '/render', json={'edit_plan': plan}).status_code == 202
        queue, store = app.extensions['job_queue'], app.extensions['job_store']
        with queue.lock:
            future = queue.active[job]
        deadline = time.monotonic() + 5
        while store.get(job)['status'] != 'rendering' and time.monotonic() < deadline:
            time.sleep(.01)
        assert store.get(job)['status'] == 'rendering'
        assert client.post('/api/jobs/' + job + '/cancel').status_code == 200
        future.result(timeout=5)
        assert store.get(job)['status'] == 'cancelled'
        assert not (tmp_path / job / 'output.mp4').exists()
        assert not list((tmp_path / job).glob('*tmp'))
        assert not list((tmp_path / job).glob('.stage-progress*'))
    finally:
        app.extensions['job_queue'].close()


def test_recovery_rejects_obsolete_plan_without_blocking_startup(setup, video):
    app, client, _ = setup
    job = upload(client, video)
    store, queue = app.extensions['job_store'], app.extensions['job_queue']
    snapshot = store.get(job)
    snapshot.update(status='queued', target='render', edit_plan={'segments': [
        {'source_start': 0, 'source_end': 1, 'video_effects': ['unsupported']}]})
    store.save(snapshot)
    queue.recover()
    assert store.get(job)['status'] == 'error'
    assert not queue.active


def test_events_are_bounded_and_json_limit_is_enforced(setup, video):
    app, client, _ = setup
    job = upload(client, video)
    store = app.extensions['job_store']
    snapshot = store.get(job)
    for _ in range(1010):
        store.save(snapshot)
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM events WHERE job_id=?', (job,)).fetchone()[0] == 1000
    app.config['MAX_JSON_BYTES'] = 100
    assert client.post('/api/jobs/' + job + '/analyze', json={'prompt': 'x' * 200}).status_code == 413


def test_gunicorn_eight_streams_leave_health_and_status_responsive(tmp_path, setup, video):
    pytest.importorskip('gunicorn')
    app, client, _ = setup
    job = upload(client, video)
    store = app.extensions['job_store']
    snapshot = store.get(job)
    snapshot.update(status='rendering')
    store.save(snapshot)
    app.extensions['job_queue'].close()
    module = tmp_path / 'stream_app.py'
    module.write_text('from server.api import create_app\napp = create_app(' + repr({
        'WORKSPACE': app.config['WORKSPACE'], 'RECOVER_JOBS': False}) + ')\n')
    # Run a local-only HTTP client in a child: ordinary tests prohibit all sockets.
    script = '''
import http.client, os, socket, subprocess, sys, time
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
process = subprocess.Popen([sys.executable, '-m', 'gunicorn', '--bind', f'127.0.0.1:{port}',
    '--workers', '1', '--threads', '16', '--pythonpath', sys.argv[1], 'stream_app:app'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
connections = []
def get(path):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    conn.request('GET', path)
    return conn, conn.getresponse()
try:
    for attempt in range(100):
        try:
            conn, response = get('/api/health')
            assert response.status == 200
            conn.close()
            break
        except OSError:
            time.sleep(.1)
    else:
        raise AssertionError('Gunicorn did not start')
    for _ in range(8):
        conn, response = get('/api/jobs/' + sys.argv[2] + '/events')
        assert response.status == 200
        connections.append((conn, response))
    started = time.monotonic()
    for path, status in [('/api/health', 200), ('/api/jobs/' + sys.argv[2], 200),
                         ('/api/jobs/' + sys.argv[2] + '/events', 429)]:
        conn, response = get(path)
        assert response.status == status
        response.read()
        conn.close()
    assert time.monotonic() - started < 2
finally:
    for conn, response in connections:
        response.close()
        conn.close()
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), job],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
