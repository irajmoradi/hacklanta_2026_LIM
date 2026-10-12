"""INT-01 orchestration contracts with synthetic media and no paid calls."""
import json
import itertools
import math
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


@pytest.mark.parametrize('preset', ['landscape', 'vertical', 'square'])
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
    assert (meta['width'], meta['height']) == {'landscape': (1920, 1080), 'vertical': (1080, 1920), 'square': (1080, 1080)}[preset]
    assert meta['audio_codec'] == 'aac'
    assert not (tmp_path / 'render_tmp').exists()
    assert job['clips'] and job['edit_plan']
    assert all(t >= 0 for t in job['timings'].values())
    client.find_clips.assert_called_once()
    client.plan_edit.assert_called_once()
    if missing:
        assert job['warnings']
    else:
        assert any('SAM model unavailable' in w for w in job['warnings'])
        assert 'spotlight_0' not in job['timings'] and 'reactions_0' in job['timings']
        assert meta['duration'] >= 1.0


def test_veto_ranking_and_merge():
    whole = [dict(start_seconds=0., end_seconds=1., description='kill')]
    assert rank_merge([candidate()], [assessment(player_alive=False)], whole) == []
    result = rank_merge([candidate()], [assessment()], whole)
    assert len(result) == 1 and result[0]['score'] == pytest.approx(.35 * (.5 + math.atan(.8) / math.pi) + .65*.9)
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


def test_unbounded_signal_scores_keep_order():
    result = rank_merge([dict(start=0, end=1, score=2), dict(start=2, end=3, score=8)], [], [])
    assert result[0]['score'] > result[1]['score']
    assert result[0]['start_seconds'] == 2
    assert all(0 < c['score'] < 1 for c in result)


def test_preparation_preserves_mixed_metadata(source, tmp_path):
    from pipeline.rendering import prepare_legacy
    job = job_for(source, tmp_path, dict(perf=False))
    plan = {'segments': [dict(source_start=0, source_end=.5, speed=.5, title='slow',
             words=[dict(start=.1, end=.2, text='word')],
             sam={'subject_track': [dict(time=.1, x=.4, y=.5)]}),
             dict(source_start=.5, source_end=1, title='unchanged', words=[dict(start=.1, end=.2, text='next')])]}
    _, prepared = prepare_legacy(Pipeline(), job, plan, tmp_path)
    a, b = prepared['segments']
    assert a['title'] == 'slow' and b['title'] == 'unchanged'
    ratio = (a['source_end']-a['source_start'])/.5
    assert a['words'][0]['start'] == pytest.approx(.1*ratio)
    assert a['sam']['subject_track'][0]['time'] == pytest.approx(.1*ratio)
    assert b['words'][0]['text'] == 'next'


@pytest.mark.parametrize('preset', ['landscape', 'vertical', 'square'])
@pytest.mark.parametrize('captions,reactions,sam', list(itertools.product([False, True], repeat=3)))
def test_preset_feature_combinations(source, tmp_path, monkeypatch, preset, captions, reactions, sam):
    pack = tmp_path / 'pack'
    pack.mkdir()
    shutil.copyfile(source, pack / 'reaction.mp4')
    (pack / 'pack.json').write_text(json.dumps({'clips': [dict(id='one', speaker='synthetic',
        label='clutch', text='wow', file='reaction.mp4', duration=.2, background='opaque')]}))
    monkeypatch.setenv('REACTION_PACK', str(pack))
    job = job_for(source, tmp_path, dict(preset=preset, captions=captions, reactions=reactions,
                                       sam=sam, privacy=False))
    job['clips'] = [dict(start_seconds=0, end_seconds=.4, score=.9, label='clutch', suggested_reaction_label='clutch')]
    job['edit_plan'] = dict(render_version=2, resolution=720, captions={'transcribe': False},
                           segments=[dict(source_start=0, source_end=.4, title='Edited caption',
                                          words=[dict(start=0, end=.3, text='caption')])])
    Pipeline().render(job, None)
    meta = probe_video(job['output'])
    assert (meta['width'], meta['height']) == {'landscape': (1280, 720), 'vertical': (720, 1280), 'square': (720, 720)}[preset]
    assert ('reactions_0' in job['timings']) is reactions
    assert 'spotlight_0' not in job['timings']
    assert any('SAM model unavailable' in w for w in job['warnings']) is sam
    assert meta['audio_codec'] == 'aac'


def test_edited_caption_burn_changes_pixels(source, tmp_path):
    import numpy as np
    outputs = []
    for enabled in (False, True):
        directory = tmp_path / str(enabled)
        directory.mkdir()
        job = job_for(source, directory, dict(captions=enabled, reactions=False, privacy=False))
        job['edit_plan'] = dict(render_version=2, resolution=720, segments=[dict(source_start=0, source_end=.5,
                                title='USER EDITED TEXT', words=[dict(start=0, end=.4, text='word')])])
        Pipeline().render(job, None)
        frame = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '0.2', '-i', job['output'], '-frames:v', '1',
                                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
        outputs.append(np.frombuffer(frame, dtype=np.uint8).reshape(720, 1280, 3).astype(float))
    assert np.abs(outputs[0][60:150]-outputs[1][60:150]).mean() > 1


@pytest.mark.parametrize('perf', [False, True])
def test_legacy_fade_chromatic_speed_audio_and_geometry(source, tmp_path, perf):
    import numpy as np
    from services.ffmpeg_runner import FFmpegRunner
    runner = FFmpegRunner(tmp_path, source, 160, 90, 10, perf=perf)
    _, path = runner._render_one_segment(0, dict(source_start=0, source_end=.5, speed=.5,
                        video_effects=['slow_motion', 'chromatic_aberration', 'fade_out']))
    meta = probe_video(path)
    assert (meta['width'], meta['height']) == (160, 90)
    assert meta['duration'] == pytest.approx(2, abs=.2)
    info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                                    capture_output=True, text=True, check=True).stdout)
    durations = [float(s['duration']) for s in info['streams']]
    assert max(durations)-min(durations) < .2
    frame = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '1.8', '-i', str(path), '-frames:v', '1',
                            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
    assert len(frame) == 160*90*3
    assert np.frombuffer(frame, dtype=np.uint8).mean() < 35


@pytest.mark.parametrize('version_key', ['version', 'render_version'])
def test_pipeline_rejects_unknown_plan_versions_before_rendering(tmp_path, version_key):
    from pipeline.rendering import _render_job
    job = dict(options={}, edit_plan={version_key: 3, 'segments': []})
    with pytest.raises(ValueError, match='Unsupported'):
        _render_job(Pipeline(), job, None)


def test_unknown_reaction_preset_before_media_io():
    from reactions.render import render_overlay, layout
    with pytest.raises(ValueError, match='preset'):
        layout(1080, 1080, 'typo')
    with pytest.raises(ValueError, match='preset'):
        render_overlay('missing.mp4', None, 'typo')


def test_explicit_caption_options_survive_toggle(source, tmp_path, monkeypatch):
    from render.engine import Renderer
    original = Renderer.render
    seen = []
    def capture(self, plan):
        seen.append(plan)
        return original(self, plan)
    monkeypatch.setattr(Renderer, 'render', capture)
    job = job_for(source, tmp_path, dict(captions=True, reactions=False, privacy=False))
    job['edit_plan'] = dict(render_version=2, resolution=720, fps=20, reframe='blur',
                           captions=dict(transcribe=False, mask_profanity=True),
                           segments=[dict(source_start=0, source_end=.3, title='Edited')])
    Pipeline().render(job, None)
    assert seen[0].captions.enabled is True
    assert seen[0].captions.transcribe is False
    assert seen[0].captions.mask_profanity is True
    assert seen[0].fps == 20 and seen[0].reframe == 'blur'
    assert not job['warnings']
