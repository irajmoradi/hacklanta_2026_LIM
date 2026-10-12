"""Integration boundaries: real local media, explicit offline providers."""
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipeline import Pipeline
from pipeline.extensions import analysis_inputs, extra_signals, planner_plan, team_source
from server.api import create_app, public
from server.validation import EXTENSION_FLAGS, options_valid
from server.legacy import EDIT_STYLES
from services.probe import probe_video


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    path = tmp_path_factory.mktemp('int02') / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=s=320x180:r=15:d=4', '-f', 'lavfi', '-i',
                    'sine=frequency=800:duration=4', '-c:v', 'libx264', '-threads', '2',
                    '-c:a', 'aac', str(path)], check=True)
    return path


def job(media, tmp_path, **options):
    return dict(source=str(media), dir=str(tmp_path), meta=probe_video(media),
                options=options, warnings=[], candidates=[], clips=[
                    dict(id='0', start_seconds=0, end_seconds=3, score=.9,
                         type='good', description='Clutch')])


@pytest.mark.parametrize('flag', sorted(EXTENSION_FLAGS))
def test_flags_are_strict_booleans(flag):
    assert options_valid({flag: True}, EDIT_STYLES)[flag]
    with pytest.raises(ValueError):
        options_valid({flag: 'true'}, EDIT_STYLES)


def test_profiles_audio_chat_and_vjepa_feed_shared_veto(media, tmp_path, monkeypatch):
    pipeline = Pipeline()
    state = job(media, tmp_path, profiles=True, game='valorant', audio_ai=True,
                vjepa=True, ingest=True, chat=[dict(time=1, activity=2, emotes=8, clip_it=1)])
    monkeypatch.delenv('VJEPA_HEAD', raising=False)
    assert analysis_inputs(pipeline, state) != str(media)
    extra_signals(pipeline, state)
    assert state['game'] == 'valorant' and state['profile_prompt']
    assert state['audio_signals']['seconds']
    assert state['vjepa_signals'] == []
    assert any('chat_clip_it' in c['signals'] for c in state['candidates'])
    assert all(0 <= c['start'] < c['end'] <= state['meta']['duration'] for c in state['candidates'])
    from pipeline.ranking import rank_merge
    veto = [dict(**c, player_alive=False, kind='neutral', hype=0) for c in state['candidates']]
    assert rank_merge(state['candidates'], veto, []) == []
    json.dumps(state, allow_nan=False)


def test_trained_head_is_required_and_signals_are_fused(media, tmp_path, monkeypatch):
    import vjepa
    pipeline = Pipeline()
    state = job(media, tmp_path, vjepa=True)
    analysis_inputs(pipeline, state)
    scorer = Mock(return_value=[dict(second=1, kill_prob=.9, sick_score=.8)])
    monkeypatch.setattr(vjepa, 'score', scorer)
    monkeypatch.delenv('VJEPA_HEAD', raising=False)
    extra_signals(pipeline, state)
    scorer.assert_not_called()
    head = tmp_path / 'trained-head'
    head.write_text('test stand-in')
    monkeypatch.setenv('VJEPA_HEAD', str(head))
    extra_signals(pipeline, state)
    scorer.assert_called_once()
    assert state['candidates'][0]['signals']['vjepa_kill'] == .9
    scorer.side_effect = ValueError('wrong game head')
    extra_signals(pipeline, state)
    assert state['vjepa_signals'] == []
    assert any('no evidence' in w for w in state['warnings'])


def test_new_planner_render_music_privacy_social_and_narration(media, tmp_path, monkeypatch):
    pipeline = Pipeline()
    state = job(media, tmp_path, planner=True, fx=True, music=True, narration=True,
                social=True, privacy_options=dict(game='valorant', backend='none', regions={}),
                style='clean_edit', max_duration=3, preset='square')
    monkeypatch.setattr(pipeline, 'client', Mock(side_effect=AssertionError('No network client needed')))
    pipeline.plan(state, None)
    assert state['planner_plan']['version'] == 2
    assert state['edit_plan']['segments'][0]['fx'][0]['name'] == 'zoom_punch'
    pipeline.render(state, None)
    assert Path(state['output']).is_file()
    assert (tmp_path / 'share' / 'video.mp4').is_file()
    assert (tmp_path / 'share' / 'metadata.json').is_file()
    assert isinstance(state['share_kit'], dict)
    assert state['share_kit']['titles'] and state['share_kit']['metadata']['platforms']
    assert state['share_kit']['covers'] == state['share_kit']['thumbnails']
    assert all(row['url'].startswith('/api/jobs/') for row in state['share_kit']['downloads'])
    assert {'privacy', 'music', 'social', 'narration', 'render_v2'} <= state['timings'].keys()
    assert probe_video(state['output'])['duration'] <= 3.15
    assert state['source'] == str(media)
    assert not (tmp_path / 'extensions_tmp').exists()
    json.dumps(state, allow_nan=False)


def test_missing_optional_modules_and_planner_fallback(media, tmp_path, monkeypatch):
    pipeline = Pipeline()
    state = job(media, tmp_path, planner=True, profiles=True, audio_ai=True, ingest=True)
    real = pipeline.hook
    monkeypatch.setattr(pipeline, 'hook', lambda *args: None)
    assert analysis_inputs(pipeline, state) == str(media)
    extra_signals(pipeline, state)
    assert planner_plan(pipeline, state) is None
    client = Mock()
    client.plan_edit.return_value = dict(segments=[dict(source_start=0, source_end=1)])
    monkeypatch.setattr(pipeline, 'client', lambda *args: client)
    pipeline.plan(state, None)
    client.plan_edit.assert_called_once()


def test_planner_clutch_speed_is_applied_once(media, tmp_path):
    state = job(media, tmp_path, planner=True, max_duration=6, style='hype_montage', privacy=False)
    state['clips'][0]['suggested_reaction_label'] = 'clutch'
    pipeline = Pipeline()
    pipeline.plan(state, None)
    assert any(s['speed'] == .5 for s in state['edit_plan']['segments'])
    assert all('slow_motion' not in s['video_effects'] for s in state['edit_plan']['segments'])
    pipeline.render(state, None)
    assert abs(probe_video(state['output'])['duration'] - state['planner_plan']['duration']) < .2


def test_repeated_uploads_are_private_and_team_render_is_composed(media, tmp_path, monkeypatch):
    from multipov import Alignment
    import multipov
    from werkzeug.datastructures import MultiDict
    app = create_app({'TESTING': True, 'WORKSPACE': str(tmp_path / 'jobs')})
    try:
        response = app.test_client().post('/api/jobs', data=MultiDict([
            ('video', (io.BytesIO(media.read_bytes()), 'first.mp4')),
            ('video', (io.BytesIO(media.read_bytes()), 'second.mp4'))]))
        assert response.status_code == 201
        assert response.json['source_count'] == 2 and 'sources' not in response.json
        state = app.extensions['job_store'].get(response.json['id'])
        state['options'] = dict(multipov=True, team_mode='split', privacy=False)
        state['edit_plan'] = dict(segments=[dict(source_start=0, source_end=1)])
        # Sync's audio algorithm has dedicated real-media tests. This fixture is
        # periodic on purpose; inject a known alignment to exercise composition.
        monkeypatch.setattr(multipov, 'sync', lambda videos: [Alignment(0), Alignment(0)])
        Pipeline().render(state, None)
        assert len(state['team_alignments']) == 2
        assert len(state['team_candidates'][0]['angles']) == 2
        assert probe_video(state['output'])['duration'] < 1.2
    finally:
        app.extensions['job_queue'].close()


def test_chat_rejects_text_and_public_hides_analysis_paths():
    assert options_valid({'privacy_options': {'backend': 'none'}}, EDIT_STYLES)['privacy_options'] == {'backend': 'none'}
    with pytest.raises(ValueError):
        options_valid({'chat': [{'time': 1, 'message': 'private'}]}, EDIT_STYLES)
    state = dict(id='a', edit_plan=None, clips=None, output=None,
                 _analysis_source='/private/proxy', _chunks=[], sources=['/private/source'])
    assert not any(k.startswith('_') for k in public(state))
    assert 'sources' not in public(state)
