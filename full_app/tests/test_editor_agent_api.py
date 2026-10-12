from copy import deepcopy
import threading

from server.api import create_app
from test_editor_agent import ScriptedModel, call


def test_chat_undo_sse_and_auth(tmp_path):
    app = create_app(dict(TESTING=True, WORKSPACE=str(tmp_path),
        API_TOKENS={'one': '1'*32, 'two': '2'*32},
        EDITOR_AGENT_MODEL_FACTORY=lambda: ScriptedModel(call('trim_clip', clip=0, t0=1, t1=3), call('finish', summary='Shorter'))))
    queue = app.extensions['job_queue']
    store = app.extensions['job_store']
    original = dict(render_version=2, segments=[dict(source_start=0, source_end=4)])
    job = dict(id='a'*32, _owner='one', dir=str(tmp_path), meta={'duration': 10},
        options={'max_duration': 10}, edit_plan=deepcopy(original), clips=[], completed=['upload', 'analyze', 'plan', 'render'],
        status='done', output='old.mp4', source='source.mp4', candidates=[], error=None)
    store.save(job)
    client = app.test_client()
    headers = {'Authorization': 'Bearer '+'1'*32}
    url = '/api/jobs/' + job['id']
    try:
        assert client.post(url+'/agent', json={'instruction': 'shorter'}, headers={'Authorization': 'Bearer '+'2'*32}).status_code == 404
        assert client.post(url+'/agent', json={'instruction': ''}, headers=headers).status_code == 400
        response = client.post(url+'/agent', json={'instruction': 'shorter'}, headers=headers)
        assert response.status_code == 200 and not response.json['fallback']
        assert response.json['plan']['segments'][0]['source_start'] == 1
        saved = store.get(job['id'])
        assert saved['output'] is None and 'render' not in saved['completed']
        assert response.json['version'] == 1
        events = client.get(url+'/events', headers=headers).text
        assert 'event: agent_step' in events and 'trim_clip' in events
        assert 'event: progress' in events
        response = client.post(url+'/agent/undo', headers=headers)
        assert response.json['plan'] == original and response.json['version'] == 2
        assert client.post(url+'/agent/undo', headers=headers).status_code == 409
    finally:
        queue.close()


def test_busy_cancel_and_recovery(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Blocking(ScriptedModel):
        def next(self, *args):
            entered.set()
            assert release.wait(10)
            return call('finish', summary='Done')
    app = create_app(dict(TESTING=True, WORKSPACE=str(tmp_path), EDITOR_AGENT_MODEL_FACTORY=Blocking))
    queue, store = app.extensions['job_queue'], app.extensions['job_store']
    job = dict(id='b'*32, dir=str(tmp_path), meta={'duration': 10}, options={},
               edit_plan=dict(render_version=2, segments=[dict(source_start=0, source_end=4)]),
               clips=[], completed=['plan'], status='planned', output=None)
    store.save(job)
    from server.editor import submit
    try:
        future = submit(queue, job['id'], 'review', Blocking)
        assert entered.wait(5)
        client = app.test_client()
        url = '/api/jobs/'+job['id']
        assert client.post(url+'/agent', json={'instruction': 'again'}).status_code == 409
        assert client.post(url+'/agent/undo').status_code == 409
        assert client.delete(url).status_code == 409
        queue.cancel(job['id'])
        release.set()
        assert future.result(timeout=10)['reason'] == 'cancelled'
        assert store.get(job['id'])['edit_plan'] == job['edit_plan']
        current = store.get(job['id'])
        current['status'] = 'editing'
        store.save(current)
        queue.recover()
        assert store.get(job['id'])['status'] == 'planned'
    finally:
        release.set()
        queue.close()


def test_opt_in_pipeline_agent(tmp_path, monkeypatch):
    import editor_agent.model
    from server.validation import options_valid
    from server.legacy import EDIT_STYLES
    from server.queue import JobQueue
    from server.store import JobStore
    monkeypatch.setattr(editor_agent.model, 'GeminiEditor', lambda: ScriptedModel(call('finish', summary='Approved')))
    class Pipeline:
        def plan(self, job, key):
            assert job['options']['planner']
            job['edit_plan'] = dict(render_version=2, segments=[dict(source_start=0, source_end=4)])
    store = JobStore(tmp_path/'jobs.sqlite3')
    queue = JobQueue(store, Pipeline())
    store.save(dict(id='c'*32, dir=str(tmp_path), meta={'duration': 10}, options={},
                    clips=[{'id': 'clip'}], candidates=[], edit_plan=None, completed=['analyze'], status='analyzed', output=None))
    try:
        options = options_valid({'editor_agent': True}, EDIT_STYLES)
        queue.submit('c'*32, 'plan', options).result(timeout=10)
        job = store.get('c'*32)
        assert job['status'] == 'planned' and not job['agent_result']['fallback']
        assert job['completed'].count('plan') == 1
        assert any('agent_step' in data for _, data in store.events(job['id'], 0))
    finally:
        queue.close()

