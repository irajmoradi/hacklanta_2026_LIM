"""INT-01 orchestration contracts with synthetic media and no paid calls."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline import Pipeline
from pipeline.ranking import rank_merge
from services.probe import probe_video


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp('pipeline-media') / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=160x90:rate=10', '-f', 'lavfi', '-i',
                    'sine=frequency=440', '-t', '2', '-c:v', 'libx264', '-c:a', 'aac', str(path)], check=True)
    return path


def candidate():
    return dict(start=0., end=1., score=.8, signals={'motion': .8}, events=[])


def assessment(**changes):
    return {**candidate(), 'player_alive': True, 'kind': 'highlight', 'hype': 9.,
            'caption': 'clutch', 'reaction': 'clutch', **changes}


def job_for(source, tmp_path, options):
    return dict(source=str(source), dir=str(tmp_path), meta=probe_video(source),
                options=options, warnings=[], candidates=[])


def provider():
    client = Mock()
    client.score_windows.return_value = [assessment()]
    client.find_clips.return_value = [dict(start_seconds=0., end_seconds=1., description='clutch')]
    client.plan_edit.return_value = {'segments': [dict(source_start=0., source_end=1.)]}
    return client


@pytest.mark.parametrize('preset', ['landscape', 'vertical'])
@pytest.mark.parametrize('missing', [None, 'signals', 'scorer', 'captions', 'reactions', 'sam', 'render'])
def test_full_optional_matrix(source, tmp_path, monkeypatch, preset, missing):
    from signals.models import Candidate
    pipeline = Pipeline()
    client = provider()
    monkeypatch.setattr(pipeline, 'client', lambda *args: client)
    detect = Mock(return_value=[Candidate(**candidate())])
    monkeypatch.setitem(sys.modules, 'signals', SimpleNamespace(detect_candidates=detect))
    if missing == 'scorer':
        client.score_windows = None
    if missing in ('signals', 'reactions', 'sam'):
        monkeypatch.setitem(sys.modules, missing, None)
    if missing == 'render':
        monkeypatch.setitem(sys.modules, 'render.engine', None)
    # Exercise real composition with synthetic reaction media, no downloaded pack.
    pack = tmp_path / 'pack'
    pack.mkdir()
    shutil.copyfile(source, pack / 'reaction.mp4')
    (pack / 'pack.json').write_text(json.dumps({'clips': [dict(id='one', speaker='synthetic',
        label='clutch', text='wow', file='reaction.mp4', duration=.3, background='opaque')]}))
    monkeypatch.setenv('REACTION_PACK', str(pack))
    if missing == 'captions':
        monkeypatch.setitem(sys.modules, 'faster_whisper', None)
    else:
        word = SimpleNamespace(start=.05, end=.4, word='clutch')
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(words=[word])], {})
        monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Mock(return_value=model)))
    options = dict(preset=preset, captions=True, sam=True, sam_reframe=True)
    job = job_for(source, tmp_path, options)
    for stage in ('analyze', 'plan', 'render'):
        getattr(pipeline, stage)(job, None)
    meta = probe_video(job['output'])
    assert (meta['width'], meta['height']) == ((1920, 1080) if preset == 'landscape' else (1080, 1920))
    assert meta['audio_codec'] == 'aac'
    assert not (tmp_path / 'render_tmp').exists()
    assert job['clips'] and job['edit_plan']
    assert all(t >= 0 for t in job['timings'].values())
    client.find_clips.assert_called_once()
    client.plan_edit.assert_called_once()
    if missing:
        assert job['warnings']
    else:
        assert not job['warnings']
        assert 'spotlight_0' in job['timings'] and 'reactions_0' in job['timings']
        assert meta['duration'] >= 1.5


def test_veto_ranking_and_merge():
    whole = [dict(start_seconds=0., end_seconds=1., description='kill')]
    assert rank_merge([candidate()], [assessment(player_alive=False)], whole) == []
    result = rank_merge([candidate()], [assessment()], whole)
    assert len(result) == 1 and result[0]['score'] == pytest.approx(.865)
    assert result[0]['sources'] == ['signals+vlm', 'whole_video']


def test_disabled_modules_are_not_loaded(source, tmp_path, monkeypatch):
    pipeline = Pipeline()
    client = provider()
    monkeypatch.setattr(pipeline, 'client', lambda *args: client)
    for name in ('signals', 'sam', 'reactions'):
        monkeypatch.setitem(sys.modules, name, None)
    job = job_for(source, tmp_path, dict(use_signals=False, window_scoring=False,
                  sam=False, sam_reframe=False, captions=False, reactions=False))
    for stage in ('analyze', 'plan', 'render'):
        getattr(pipeline, stage)(job, None)
    assert not job['warnings']
    client.score_windows.assert_not_called()


def test_stage_events(source, tmp_path, monkeypatch):
    pipeline = Pipeline()
    monkeypatch.setattr(pipeline, 'client', lambda *args: provider())
    job = job_for(source, tmp_path, dict(use_signals=False))
    events = []
    pipeline.run_stage('analyze', job, None, lambda j: events.append(j['pipeline_stage']))
    assert events == [name for name in ('probe', 'signals', 'window_scoring', 'whole_video', 'rank_merge') for _ in range(2)]


def test_legacy_speed_still_uses_v2(source, tmp_path):
    job = job_for(source, tmp_path, dict(preset='vertical', reactions=False))
    job['edit_plan'] = {'segments': [dict(source_start=0., source_end=1., speed=.5)]}
    Pipeline().render(job, None)
    meta = probe_video(job['output'])
    assert 1.8 < meta['duration'] < 2.3
    assert (meta['width'], meta['height']) == (1080, 1920)
    assert 'legacy_effects' in job['timings'] and 'render_v2' in job['timings']


def test_failed_optional_callable_does_not_hide_errors(source, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'signals', SimpleNamespace(detect_candidates=Mock(side_effect=RuntimeError('decoder'))))
    job = job_for(source, tmp_path, {})
    with pytest.raises(RuntimeError, match='decoder'):
        Pipeline().analyze(job, None)


def test_explicit_v2_plan_without_renderer(source, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'render.engine', None)
    job = job_for(source, tmp_path, {})
    job['edit_plan'] = {'render_version': 2, 'segments': [dict(source_start=0., source_end=1.)]}
    Pipeline().render(job, None)
    meta = probe_video(job['output'])
    assert (meta['width'], meta['height']) == (1920, 1080)
    assert job['warnings']
    assert job['edit_plan']['render_version'] == 2
