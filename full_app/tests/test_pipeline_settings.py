"""Real HTTP/queue settings flow with a fake provider and synthetic media."""
import io
import time
from unittest.mock import Mock

from pipeline import Pipeline
from server.api import create_app
from services.probe import probe_video


def wait(app, job_id):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = app.extensions['job_store'].get(job_id)
        if state['status'] not in ('queued', 'analyzing', 'planning', 'rendering'):
            return state
        time.sleep(.02)
    raise AssertionError('Job did not finish')


def test_saved_caption_and_changed_style_reach_render(video, tmp_path, monkeypatch):
    pipeline = Pipeline()
    provider = Mock()
    provider.find_clips.return_value = [dict(start_seconds=0, end_seconds=.5, description='original')]
    provider.plan_edit.side_effect = lambda prompt: dict(resolution=720, segments=[dict(
        source_start=0, source_end=.5, words=[dict(start=0, end=.4, text='word')])])
    monkeypatch.setattr(pipeline, 'client', lambda *args: provider)
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path / 'jobs')}, pipeline)
    client = app.test_client()
    try:
        response = client.post('/api/jobs', data={'video': (io.BytesIO(video.read_bytes()), 'synthetic.mp4')})
        job_id = response.json['id']
        url = '/api/jobs/' + job_id
        assert client.post(url + '/analyze', json=dict(style='clean_edit', use_signals=False,
                           privacy=False, captions=False, reactions=False, sam=False)).status_code == 202
        state = wait(app, job_id)
        assert state['status'] == 'planned'
        reviewed = [{**state['clips'][0], 'caption': 'USER EDITED TITLE'}]
        assert client.patch(url + '/clips', json={'clips': reviewed}).status_code == 200
        assert client.post(url + '/render', json=dict(style='meme_edit', preset='square', captions=True,
                           reactions=False, sam=False)).status_code == 202
        state = wait(app, job_id)
        assert state['status'] == 'done', state
        assert provider.plan_edit.call_count == 2
        assert provider.plan_edit.call_args_list[0] != provider.plan_edit.call_args_list[1]
        assert state['planning_settings']['style'] == 'meme_edit'
        assert state['options']['captions'] is True
        assert state['edit_plan']['segments'][0]['title'] == 'USER EDITED TITLE'
        assert any(e['text'] == 'USER EDITED TITLE' for e in state['subtitle_events'])
        assert probe_video(state['output'])['width'] == 720
    finally:
        app.extensions['job_queue'].close()
