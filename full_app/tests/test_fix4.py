"""Demo-shaped regressions; generated footage only, no paid calls."""
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from models.schemas import ClipList
from pipeline import Pipeline
from pipeline.ranking import bounded_clips
from server.api import create_app
from server.legacy import EDIT_STYLES
from server.validation import options_valid
from services.call_budget import CallBudget
from services.provider_errors import ProviderFailure, classify
from services.response_schema import compatible_schema, parse_response


def test_all_profile_consumers_accept_generic_and_league():
    from profiles import list_profiles
    from signals.ocr import regions_for
    from privacy.profiles import regions_for as private_regions
    from privacy import PrivacyOptions
    for name in list_profiles():
        assert regions_for(name)
        assert private_regions(PrivacyOptions(game=name))


def test_capability_contract(tmp_path):
    app = create_app(dict(TESTING=True, WORKSPACE=str(tmp_path)))
    try:
        caps = app.test_client().get('/api/info').json['frontend_capabilities']
        assert all(caps['modules'][name] for name in ('planner', 'privacy', 'social', 'profiles'))
        assert {'planner_v2', 'privacy_blur', 'share_kit', 'game'} <= set(caps['options'])
        parsed = options_valid(dict(planner_v2=True, privacy_blur=True, share_kit=True, game='generic'), EDIT_STYLES)
        assert parsed == dict(planner=True, privacy=True, social=True, game='generic', profiles=True)
        with pytest.raises(ValueError):
            options_valid(dict(planner=True, planner_v2=False), EDIT_STYLES)
        assert caps['url_import'] is False
    finally:
        app.extensions['job_queue'].close()


def test_dense_interest_uses_fusion_not_candidates(video):
    from signals import detect_candidates
    curves = []
    candidates = detect_candidates(video, profile='generic', curve_sink=curves.append)
    curve = curves[0]
    assert len(curve) == 6
    assert [r['time'] for r in curve] == list(range(6))
    assert all(0 <= r['score'] <= 100 for r in curve)
    assert max(r['score'] for r in curve) == 100


def test_sdk_schema_and_strict_per_item_admission():
    from google.genai import types
    schema = compatible_schema(ClipList.model_json_schema())
    assert 'exclusiveMinimum' not in json.dumps(schema)
    # Actual SDK schema conversion, not just a mocked generate_content call.
    from google.genai import _transformers
    client = Mock(vertexai=True)
    _transformers.t_schema(client, schema)
    good = dict(start=1., end=3., start_seconds=1., end_seconds=3., type='good', description='Play')
    result = parse_response(ClipList, json.dumps({'clips': [good, {**good, 'end': 0}, {**good, 'type': 'invented'}]}))
    assert len(result.clips) == 1
    with pytest.raises(ValidationError):
        ClipList.model_validate({'clips': [{**good, 'end': 0}]})


def test_demo_timestamp_shapes_are_isolated(caplog):
    ranges = [(10, 20), (2636, 2640), (2802, 2807), (1860, 1890), (-2, 5), (5, 5)]
    result = bounded_clips([dict(start_seconds=a, end_seconds=b) for a, b in ranges], 1871.970)
    assert [(r['start_seconds'], r['end_seconds']) for r in result] == [(10, 20), (1860, 1871.970), (0, 5)]
    assert 'Dropped' in caplog.text and 'Clamped' in caplog.text


def test_budget_parallel_durable_and_separate_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_REQUEST_INTERVAL_SECONDS', '0')
    path = tmp_path / 'budget.sqlite3'
    def reserve(_):
        try:
            CallBudget(path, limit=3).reserve()
            return True
        except ProviderFailure:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 3
    assert CallBudget(path, limit=3).remaining == 0
    assert CallBudget(tmp_path / 'other.sqlite3', limit=3).remaining == 3
    monkeypatch.delenv('MAX_GEMINI_CALLS_PER_JOB', raising=False)
    assert CallBudget().limit == 80


def test_safe_error_messages():
    error = RuntimeError('secret-key=https://private.invalid')
    error.code = 403
    assert 'API key' in str(classify(error))
    assert 'secret' not in str(classify(error))
    assert 'budget' in str(ProviderFailure('budget'))


def test_selected_privacy_cache_and_source_clocks(video, tmp_path, monkeypatch):
    from pipeline.privacy_ranges import selected_source
    from services.probe import probe_video
    import privacy
    actual = privacy.sanitize
    calls = []
    def sanitize(source, output, payload):
        calls.append((probe_video(source)['duration'], payload))
        return actual(source, output, payload)
    monkeypatch.setattr(privacy, 'sanitize', sanitize)
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    job = dict(dir=str(tmp_path), source=str(video), options={}, meta=probe_video(video), warnings=[],
               edit_plan={'segments': [dict(source_start=2., source_end=3.)]},
               clips=[dict(start_seconds=2., end_seconds=3., description='Play')])
    pipeline = Pipeline()
    source, plan, clips = selected_source(pipeline, job, scratch)
    assert probe_video(source)['duration'] < 1.2
    assert calls[0][0] < 1.2
    assert calls[0][1]['backend'] == 'none'
    assert set(calls[0][1]['regions']) == {'kill_feed', 'chat', 'party_voice'}
    assert plan['segments'][0]['source_start'] == clips[0]['start_seconds'] == 0
    selected_source(pipeline, job, scratch)
    assert len(calls) == 1
    assert job['edit_plan']['segments'][0]['source_start'] == 2


def test_mode_change_keeps_analysis_and_never_calls_provider(video, tmp_path, monkeypatch):
    from services.probe import probe_video
    pipeline = Pipeline()
    monkeypatch.setattr(pipeline, 'client', Mock(side_effect=AssertionError('No paid calls')))
    app = create_app(dict(TESTING=True, WORKSPACE=str(tmp_path)), pipeline)
    try:
        client = app.test_client()
        with video.open('rb') as media:
            uploaded = client.post('/api/jobs', data={'video': (media, 'test.mp4')}).json
        store, queue = app.extensions['job_store'], app.extensions['job_queue']
        job = store.get(uploaded['id'])
        clips = [dict(id='0', start_seconds=0., end_seconds=2., score=.8, type='good', description='Play'),
                 dict(id='1', start_seconds=3., end_seconds=5., score=.7, type='bad', description='Whiff')]
        job.update(clips=clips, candidates=[dict(start=0, end=2, score=3)], window_scores=[{'hype': 8}],
                   interest_curve=[dict(time=i, score=i*10) for i in range(6)],
                   options=dict(mode='nice', style='clean_edit', max_duration=4),
                   completed=['upload', 'analyze', 'plan'], edit_plan={'segments': [dict(source_start=0., source_end=2.)]})
        store.save(job)
        future = queue.submit(job['id'], 'plan', {'mode': 'mean'})
        future.result(timeout=30)
        result = store.get(job['id'])
        assert result['status'] == 'planned', result.get('error')
        for name in ('clips', 'candidates', 'window_scores', 'interest_curve'):
            assert result[name] == job[name]
        pipeline.client.assert_not_called()
    finally:
        app.extensions['job_queue'].close()
