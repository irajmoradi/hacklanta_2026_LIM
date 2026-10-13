"""Feature coverage over HTTP with fake inference and real synthetic media/FFmpeg."""
import io
import json
import shutil
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline import Pipeline
from server.api import create_app
from server.legacy import EDIT_STYLES
from server.validation import options_valid


def wait(app, job_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = app.extensions['job_store'].get(job_id)
        if job['status'] not in ('queued', 'analyzing', 'planning', 'rendering'):
            assert job['status'] != 'error', job.get('error')
            return job
        time.sleep(.05)
    raise AssertionError('Job timed out')


def test_full_experience_http_feature_coverage(video, tmp_path, monkeypatch):
    import render.engine
    from render.plan import Word
    import sam
    import narration.providers

    pack = tmp_path / 'pack'
    pack.mkdir()
    shutil.copyfile(video, pack / 'reaction.mp4')
    (pack / 'pack.json').write_text(json.dumps({'clips': [dict(id=str(i), speaker=f'speaker-{i}',
        label=label, text='Synthetic reaction', file='reaction.mp4', duration=.5, background='opaque')
        for i, label in enumerate(('bruh', 'fail', 'funny'))]}))
    monkeypatch.setenv('REACTION_PACK', str(pack))
    monkeypatch.setenv('SAM_BACKEND', 'local')
    # Fake segmentation only; the real compositor and overlay renderer still run.
    original_masks = sam.clip_masks
    monkeypatch.setattr(sam, 'clip_masks', lambda *a, **k: SimpleNamespace(degraded=False))
    import sam.effects
    monkeypatch.setattr(sam.effects, 'clip_masks', lambda *a, **k: original_masks(*a, **{**k, 'config': sam.Config()}))
    import sam.targeting
    monkeypatch.setattr(sam.targeting, 'target_masks', lambda source, start, end, kill_time, **kw:
                        original_masks(source, start, end, config=sam.Config()))
    monkeypatch.setattr(sam, 'subject_track', lambda source, start, end: [(start, .45, .5, .2, .3), (end-.1, .55, .5, .2, .3)])
    monkeypatch.setattr(render.engine, 'transcribe', lambda *a: [Word(start=.05, end=.4, text='spoken')])
    voice = tmp_path / 'voice.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=0.35:sample_rate=24000', str(voice)], check=True)
    monkeypatch.setattr(narration.providers, 'local_synthesize', lambda *a: voice)
    pipeline = Pipeline()
    model = Mock()
    model.find_clips.return_value = [dict(start_seconds=i*2, end_seconds=(i+1)*2,
        type='bad', description='Missed the shot', score=.9) for i in range(3)]
    monkeypatch.setattr(pipeline, 'client', lambda *a: model)
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path / 'jobs')}, pipeline)
    client = app.test_client()
    try:
        job_id = client.post('/api/jobs', data={'video': (io.BytesIO(video.read_bytes()), 'test.mp4')}).json['id']
        url = '/api/jobs/' + job_id
        assert client.post(url+'/analyze', json=dict(full_experience=True, use_signals=False,
            window_scoring=False, profiles=False, audio_ai=False, ai_cards=False,
            mode='mean', max_duration=6)).status_code == 202
        planned = wait(app, job_id)
        assert planned['options']['privacy'] is False
        assert planned['edit_plan']['intro'] and planned['edit_plan']['outro']
        assert planned['edit_plan']['transition'] == 'varied'
        assert all(s['reactions'] for s in planned['edit_plan']['segments'])
        # Keep the integration fixture small without adding an HTTP resolution option.
        planned['edit_plan']['resolution'] = 720
        app.extensions['job_store'].save(planned)
        assert client.post(url+'/render', json={}).status_code == 202
        job = wait(app, job_id)
        evidence, plan = job['render_evidence'], job['render_plan']
        graphs = '\n'.join(evidence['filter_graphs'])
        assert 'xfade=transition=zoomin' in graphs and 'xfade=transition=slideleft' in graphs
        assert 'sidechaincompress' in graphs and 'ass=' in graphs
        assert plan['music']['beat_sync'] and plan['music']['beats']
        assert all(s['words'] and s['sam']['subject_track'] for s in plan['segments'])
        assert len(evidence['reactions']) == len(plan['segments'])
        assert len({r['speaker'] for r in evidence['reactions']}) == min(3, len(plan['segments']))
        assert evidence['sam'] and evidence['privacy'] is False
        assert any(s['has_audio'] for s in job['narration_track'])
        assert job['share_kit']['downloads']
        assert evidence['output']['audio_codec'] == 'aac'
        assert model.find_clips.call_count == 1 and model.plan_edit.call_count == 0
        assert client.get('/api/search?q=shot').json['total'] == 3
        assert client.get('/api/stats/players').status_code == 200
        shared = client.post(url+'/share-page', json={})
        assert shared.status_code == 201
        assert client.get(shared.json['url']).status_code == 200
    finally:
        app.extensions['job_queue'].close()


def test_full_experience_explicit_overrides():
    result = options_valid(dict(full_experience=True, captions=False, privacy=True, music=False), EDIT_STYLES)
    assert result['privacy'] is True and result['captions'] is False and result['music'] is False
    assert options_valid(dict(full_experience=True), EDIT_STYLES)['privacy'] is False
    assert options_valid(dict(full_experience=True, privacy_blur=True), EDIT_STYLES)['privacy'] is True
    with pytest.raises(ValueError):
        options_valid(dict(full_experience='true'), EDIT_STYLES)


@pytest.mark.parametrize('rejected', [False, True])
def test_spotlight_evidence_distinguishes_strict_rejection(video, tmp_path, monkeypatch, rejected):
    import sam
    import warnings
    from services.probe import probe_video
    monkeypatch.setenv('SAM_BACKEND', 'local')
    monkeypatch.setattr(sam, 'clip_masks', lambda *a, **k: SimpleNamespace(degraded=False))
    def effect(source, output, *args, **kwargs):
        shutil.copyfile(source, output)
        if rejected:
            warnings.warn('SAM spotlight skipped: fragmented', RuntimeWarning)
    monkeypatch.setattr(sam, 'render_effect', effect)
    job = dict(source=str(video), dir=str(tmp_path), meta=probe_video(video), clips=[], warnings=[],
        options=dict(sam=True, captions=False), edit_plan=dict(render_version=2, resolution=720,
        fps=10, segments=[dict(source_start=0, source_end=.5)]))
    Pipeline().render(job, None)
    assert bool(job['render_evidence']['sam']) is not rejected
    assert bool(job['render_evidence']['sam_skipped']) is rejected


def test_unavailable_features_are_reported_and_silent_video_has_word_fallback(video, tmp_path, monkeypatch):
    from services.probe import probe_video
    silent = tmp_path / 'silent.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-an', '-c:v', 'copy', str(silent)], check=True)
    monkeypatch.delenv('REACTION_PACK', raising=False)
    monkeypatch.setenv('SAM_BACKEND', 'fallback')
    job = dict(source=str(silent), dir=str(tmp_path), meta=probe_video(silent), clips=[], warnings=[],
        options=dict(captions=True, reactions=True, sam=True, narration=True, privacy=False),
        edit_plan=dict(render_version=2, resolution=720, segments=[dict(source_start=0, source_end=.6, title='Editorial fallback')]))
    Pipeline().render(job, None)
    assert not job['render_plan']['segments'][0]['words']  # no fake per-word transcript from editorial text
    assert any('no speech words' in w for w in job['warnings'])
    assert any('REACTION_PACK' in w for w in job['warnings'])
    assert any('SAM model unavailable' in w for w in job['warnings'])
    assert any('Narration requested but no audio' in w for w in job['warnings'])


def test_library_is_owner_scoped(tmp_path):
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path), 'API_TOKENS': {'alice': 'a'*32, 'bob': 'b'*32}})
    try:
        app.extensions['job_store'].save(dict(id='one', _owner='alice', created_at=time.time(), game='generic',
            clips=[dict(id='c', start_seconds=0, end_seconds=1, description='secret clutch')]))
        client = app.test_client()
        assert client.get('/api/search?q=secret', headers={'Authorization': 'Bearer ' + 'a'*32}).json['total'] == 1
        assert client.get('/api/search?q=secret', headers={'Authorization': 'Bearer ' + 'b'*32}).json['total'] == 0
    finally:
        app.extensions['job_queue'].close()
