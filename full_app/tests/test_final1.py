"""FINAL-1 contracts; synthetic media and no paid inference."""
import copy
import io
from pathlib import Path
from unittest.mock import Mock

import pytest

from pipeline import Pipeline
from pipeline.extensions import planner_plan
from reactions import Reaction, ReactionSelector
from reactions.render import layout
from server.api import create_app
from server.legacy import EDIT_STYLES
from server.validation import options_valid
from test_wire1 import wait


@pytest.mark.parametrize('options', [{'chaos': -1}, {'chaos': 1.1}, {'chaos': True},
    {'chaos': float('nan')}, {'seed': True}, {'seed': 1.5}, {'seed': -1},
    {'seed': 2**32}, {'clean': 'yes'}, {'reaction_size': 'huge'}])
def test_invalid_options(options):
    with pytest.raises(ValueError):
        options_valid(options, EDIT_STYLES)


def test_event_forwarding_and_reproducibility():
    from planner import plan_edit
    captured = []
    def planner(clips, **options):
        captured.append(copy.deepcopy(clips))
        return plan_edit(clips, **options)
    pipeline = Mock()
    pipeline.hook.return_value = planner
    job = dict(options=dict(planner=True, seed=44, chaos=.8, max_duration=8), clips=[
        dict(id='a', start_seconds=0, end_seconds=10, score=.9, type='good',
             events=[dict(type='kill', time=5), dict(type='headshot', time=5.2)],
             signals={'events': [dict(kind='ability', time=3)]})])
    first = planner_plan(pipeline, job)
    assert [e['kind'] for e in captured[0][0]['signals']['events']] == ['ability', 'kill', 'headshot']
    assert job['seed'] == 44
    assert first == planner_plan(pipeline, job)
    job['options']['seed'] = 45
    second = planner_plan(pipeline, job)
    assert first['segments'] != second['segments']
    assert [(s['source_start'], s['source_end']) for s in first['segments']] == [
        (s['source_start'], s['source_end']) for s in second['segments']]


def test_http_reroll_keeps_analysis_and_never_calls_provider(video, tmp_path):
    pipeline = Pipeline()
    pipeline.client = Mock(side_effect=AssertionError('No provider allowed'))
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path/'jobs')}, pipeline)
    try:
        client = app.test_client()
        ident = client.post('/api/jobs', data={'video': (io.BytesIO(video.read_bytes()), 'test.mp4')}).json['id']
        store = app.extensions['job_store']
        job = store.get(ident)
        job.update(completed=['analyze'], status='analyzed', clips=[dict(id='a', start_seconds=0,
            end_seconds=5, score=.9, type='good', events=[dict(type='kill', time=3)])])
        store.save(job)
        url = '/api/jobs/'+ident
        for seed in (11, 12, 11):
            assert client.post(url+'/plan', json={'chaos': .7, 'seed': seed}).status_code == 202
            result = wait(app, ident)
            assert result['clips'] == job['clips']
            assert result['completed'] == ['analyze', 'plan']
            assert client.get(url).json['seed'] == seed
            if seed == 11 and 'first' not in locals():
                first = result['edit_plan']
            elif seed == 11:
                assert result['edit_plan'] == first
            else:
                assert result['edit_plan'] != first
        pipeline.client.assert_not_called()
    finally:
        app.extensions['job_queue'].close()


def test_explicit_policy_and_four_speaker_rotation():
    pack = [Reaction(f'{speaker}-{label}-{explicit}', speaker, label, 'line', Path('unused'), 1,
                     'light', explicit=explicit, style='genalpha')
            for speaker in ('A', 'B', 'C', 'D') for label in ('hype', 'bruh', 'clutch', 'roast')
            for explicit in (False, True)]
    for mode in ('nice', 'mean'):
        selector = ReactionSelector(pack, seed=4, cover_speakers=True, clean=True)
        selected = [selector.select(label, mode=mode) for label in ('hype', 'bruh', 'clutch', 'hype')]
        assert len({r.speaker for r in selected}) == 4
        assert all(not r.explicit and r.style == 'genalpha' for r in selected)
        assert len({r.label for r in selected}) >= 3
    assert not ReactionSelector(pack, seed=1).select(mode='nice').explicit
    explicit_only = [r for r in pack if r.explicit]
    assert ReactionSelector(explicit_only, clean=True).select(mode='mean') is None
    assert ReactionSelector(explicit_only).select(mode='mean').explicit


@pytest.mark.parametrize('preset,w,h,low,high', [('landscape',1920,1080,.28,.35),
    ('vertical',1080,1920,.22,.28), ('square',1080,1080,.28,.35)])
def test_visible_head_layout(preset,w,h,low,high):
    large,x,y = layout(w,h,preset)
    assert low <= large/min(w,h) <= high
    assert y+large > h and y > h/2
    assert layout(w,h,preset,'small')[0] < layout(w,h,preset,'medium')[0] < large


def test_sam_sample_budget_configuration(monkeypatch):
    from sam import Config
    monkeypatch.setenv('SAM_MAX_SAMPLES', '4')
    assert Config.from_env().max_samples == 4
    monkeypatch.setenv('SAM_MAX_SAMPLES', '0')
    with pytest.raises(ValueError):
        Config.from_env()
