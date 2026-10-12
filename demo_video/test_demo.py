"""Offline regression tests. No credential or live provider is used."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from budget import Budget


def test_budget_is_persistent_and_counts_failed_requests(tmp_path):
    path = tmp_path / 'calls.json'
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise ValueError('mock failure')
    for _ in range(5):
        try:
            Budget(path, 120).wrap(fail)(model='mock')
        except (RuntimeError, ValueError):
            pass
    assert len(calls) == len(json.loads(path.read_text())) == 3


def test_budget_concurrent(tmp_path):
    budget = Budget(tmp_path / 'calls.json')
    def reserve(_):
        try:
            return budget.reserve('mock')
        except RuntimeError:
            return 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sorted(pool.map(reserve, range(10))) == [0]*7 + [1, 2, 3]


def test_baseline_generic_profile_contract():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'full_app'))
    from signals.ocr import regions_for
    with pytest.raises(ValueError, match='unknown game profile: generic'):
        regions_for('generic', None)


def test_sdk_schema_adapter_and_strict_response_validation(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMO_OUT', str(tmp_path / 'out'))
    from live_smoke_server import compatible_schema, CombinedAssessment, DemoClient
    from google.genai import types
    from models.schemas import ClipList
    from pydantic import ValidationError
    value = compatible_schema(CombinedAssessment.model_json_schema())
    assert 'exclusiveMinimum' not in json.dumps(value)
    types.GenerateContentConfig(response_json_schema=value)
    from unittest.mock import patch
    from google.genai.models import Models
    with DemoClient('offline-not-a-key') as client:
        with patch.object(client.client.models._api_client, 'request', side_effect=RuntimeError('mocked transport')):
            with pytest.raises(RuntimeError, match='mocked transport'):
                Models.generate_content(client.client.models, model='gemini-3.5-flash-lite', contents=['offline'],
                    config=client._generation_config(CombinedAssessment, .3, True))
    with pytest.raises(ValidationError):
        ClipList.model_validate({'clips':[dict(start=0.,start_seconds=0.,end=0.,end_seconds=0.,type='good',description='invalid')]})


def test_selected_privacy_timeline_preserves_speed_order_and_metadata():
    from live_smoke_server import remap_selected
    plan = {'segments':[{'source_start':20.,'source_end':24.,'speed':.5},
                        {'source_start':10.,'source_end':13.,'speed':1.}]}
    clips = [dict(id='a',start_seconds=19.,end_seconds=23.,score=.8),
             dict(id='b',start_seconds=10.,end_seconds=13.,score=.4)]
    mapped, metadata, ranges = remap_selected(plan, clips)
    assert ranges == [(20.,24.),(10.,13.)]
    assert mapped['segments'] == [dict(source_start=0.,source_end=4.,speed=.5),
                                  dict(source_start=4.,source_end=7.,speed=1.)]
    assert [(c['start_seconds'],c['end_seconds'],c['score']) for c in metadata] == [(0.,3.,.8),(4.,7.,.4)]
    assert plan['segments'][0]['source_start'] == 20.
    assert clips[0]['start_seconds'] == 19.


def test_interest_curve_preserves_unbounded_signal_score_variation(tmp_path):
    from live_smoke_server import wire_job
    data = {'job_id':'offline','candidates':[{'start':0.,'end':2.,'score':2.},
                                           {'start':4.,'end':6.,'score':4.}]}
    result=wire_job(data,tmp_path)
    assert result['interest_curve']==[{'time':1.,'score':50.},{'time':5.,'score':100.}]


def test_video_compositor_with_synthetic_media(tmp_path):
    import assemble
    assemble.EDIT = tmp_path
    image = assemble.card('test', 'SYNTHETIC QA', 'Readable title', ['A synthetic test card.'])
    output = assemble.still('card', image, .5)
    metadata = assemble.probe(output)
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    assert (video['width'], video['height'], video['codec_name']) == (1920, 1080, 'h264')
    assert any(s['codec_type'] == 'audio' for s in metadata['streams'])
    assert .45 <= float(metadata['format']['duration']) <= .6


def test_real_api_adapter_offline(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMO_OUT', str(tmp_path / 'out'))
    from live_smoke_server import make_app
    from server.api import public
    source = tmp_path / 'test.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15',
                    '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '2', '-c:v', 'libx264',
                    '-threads', '1', '-c:a', 'aac', str(source)], check=True)
    class Offline:
        def analyze(self, job, key):
            job['clips'] = [dict(id='a', start_seconds=0., end_seconds=1., description='Mock event')]
            job['candidates'] = [dict(start=0., end=1., score=.8, signals={'rms': .8})]
        def plan(self, job, key):
            job['edit_plan'] = dict(segments=[dict(source_start=0., source_end=1.)])
    app = make_app(tmp_path / 'jobs', Offline())
    client = app.test_client()
    try:
        assert 'privacy_blur' in client.get('/api/info').json['frontend_capabilities']['options']
        with source.open('rb') as video:
            response = client.post('/api/jobs', data={'video': (video, 'test.mp4')})
        assert response.status_code == 201
        job_id = response.json['id']
        response = client.post(f'/api/jobs/{job_id}/analyze', json=dict(game='auto', planner_v2=True, privacy_blur=True, share_kit=True))
        assert response.status_code == 202
        queue = app.extensions['job_queue']
        with queue.lock:
            future = queue.active.get(job_id)
        if future:
            future.result(timeout=10)
        result = client.get(f'/api/jobs/{job_id}').json
        assert result['options']['profiles'] and result['options']['planner']
        assert result['options']['privacy'] and result['options']['social']
        assert result['interest_curve'] == [{'time': .5, 'score': 80.}]
        assert result['source_url'] == f'/api/stream/{job_id}'
        assert result['status'] != 'error'
    finally:
        app.extensions['job_queue'].close()
