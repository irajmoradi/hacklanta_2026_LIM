"""Offline parity contracts: API admission, instructions, images, and label mix."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_jobs import setup, video, upload, wait
from server.validation import options_valid
from server.legacy import EDIT_STYLES
from pipeline.orchestrator import Pipeline, RUNTIME_KEY
from pipeline.extensions import planner_plan, finish_output
from planner import plan_edit


def test_ui_option_contract_and_capabilities(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    options = dict(prompt='Keep the saves.\nGame: deadlock. Profile: balanced.',
                   editing_instructions='Use short captions', max_duration=30,
                   preset='vertical', planner=True, plan_refinement=True, gemini_image=True)
    assert client.post(f'/api/jobs/{job}/analyze', json=options).status_code == 202
    stored = wait(app, job)
    assert stored['options'].items() >= options.items()
    assert stored['source_filename'] == 'evil.mp4'
    assert stored['source_size'] == len(video)
    advertised = client.get('/api/info').json['frontend_capabilities']['options']
    assert {'gemini_image', 'plan_refinement'} <= set(advertised)
    for bad in ({'gemini_image': 'yes'}, {'plan_refinement': 1}, {'editing_instructions': []},
                {'editing_instructions': 'x' * 8001}):
        with pytest.raises(ValueError):
            options_valid(bad, EDIT_STYLES)


def test_plan_import_is_atomic_typed_and_does_not_call_providers(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    route = f'/api/jobs/{job}/plan'
    plan = dict(render_version=2, fps=30, segments=[dict(source_start=0, source_end=2, title='Keep this')])
    result = client.put(route, json=dict(edit_plan=plan, max_duration=10))
    assert result.status_code == 200
    assert result.json['edit_plan'] == plan
    for invalid in ({**plan, 'music': '/etc/passwd'}, {**plan, 'unknown': True},
                    {**plan, 'segments': [dict(source_start=0, source_end=20)]}):
        assert client.put(route, json=dict(edit_plan=invalid, max_duration=10)).status_code == 400
        assert client.get(f'/api/jobs/{job}').json['edit_plan'] == plan
    assert not pipeline.calls
    assert client.post(f'/api/jobs/{job}/render', json={'max_duration': 10}).status_code == 202
    assert wait(app, job)['status'] == 'done'
    assert pipeline.calls == ['render']


def test_refresh_plan_and_log_include_latest_events(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    client.post(f'/api/jobs/{job}/analyze', json={})
    wait(app, job)
    client.post(f'/api/jobs/{job}/plan', json={})
    wait(app, job)
    assert pipeline.calls == ['analyze', 'plan', 'plan']
    for i in range(120):
        app.extensions['job_store'].append_event(job, 'test', {'step': i})
    assert '"step": 119' in client.get(f'/api/log/{job}').text


@pytest.mark.parametrize('mode,preferred', [('nice', 'highlight'), ('mean', 'lowlight')])
def test_label_duration_ratio_and_shortages(mode, preferred):
    clips = [dict(id=str(i), start=i*20, end=i*20+10, score=i,
                  label='highlight' if i % 2 else 'lowlight', signals={'kind': str(i)}) for i in range(20)]
    result = plan_edit(clips, mode=mode, target_length=60, max_clip_length=10, fill_target=True)
    assert result.duration == pytest.approx(60)
    assert sum(c.duration for c in result.clips if c.label == preferred) == pytest.approx(42)
    assert result == plan_edit(reversed(clips), mode=mode, target_length=60, max_clip_length=10, fill_target=True)
    scarce = plan_edit([c for c in clips if c['label'] == preferred], mode=mode, target_length=60, fill_target=True)
    assert all(c.label == preferred for c in scarce.clips)
    assert any('70/30' in note for note in scarce.notes)


def test_analysis_instructions_reach_analysis(monkeypatch):
    seen = []
    monkeypatch.setattr('pipeline.orchestrator._analyze_segment',
        lambda segment, template, part, prompt, client: seen.append(prompt) or {'clips': []})
    Pipeline().whole_video(dict(options={'prompt': 'Look for objective saves'}, meta={'duration': 30},
                               source='synthetic.mp4', candidates=[], profile_prompt='Deadlock profile'), Mock())
    assert 'Look for objective saves' in seen[0] and 'Deadlock profile' in seen[0]


def planning_job(tmp_path):
    return dict(id='job', dir=str(tmp_path), options={'planner': True, 'max_duration': 20},
                meta={'duration': 100}, warnings=[], clips=[dict(id=str(i), start_seconds=i*20,
                    end_seconds=i*20+10, source='whole_video', type='good', score=.8, description='save') for i in range(4)])


def test_refinement_receives_editing_instructions_and_closes_client(tmp_path, monkeypatch):
    job = planning_job(tmp_path)
    job['options'].update(plan_refinement=True, editing_instructions='Use understated captions')
    client = Mock()
    client._generate.return_value.model_dump.return_value = {'captions': [{'text_index': 0, 'content': 'Saved!'}]}
    factory = Mock(return_value=client)
    monkeypatch.setattr('services.gemini_client.GeminiVideoClient', factory)
    result = planner_plan(Pipeline(), job, 'runtime-test-key')
    assert result['segments']
    assert 'Use understated captions' in client._generate.call_args.args[0][0]
    assert Path(client.budget.path) == tmp_path / 'gemini-budget.sqlite3'
    client.close.assert_called_once()
    assert 'runtime-test-key' not in json.dumps(job)


def test_editing_instructions_are_first_director_instruction(setup, video, monkeypatch):
    app, client, pipeline = setup
    run = Mock(return_value={'fallback': True, 'plan': None, 'trace': []})
    monkeypatch.setattr('server.editor.run', run)
    job = upload(client, video)
    assert client.post(f'/api/jobs/{job}/analyze', json={'planner': True,
        'editing_instructions': 'Start quietly, end with the save', 'prompt': 'Find saves'}).status_code == 202
    assert wait(app, job)['status'] == 'planned'
    assert run.call_args.args[2] == 'Start quietly, end with the save'
    assert client.post(f'/api/jobs/{job}/plan', json={'editing_instructions': 'Short captions'}).status_code == 202
    wait(app, job)
    assert pipeline.calls == ['analyze', 'plan', 'plan']
    assert run.call_args.args[2] == 'Short captions'


@pytest.mark.parametrize('enabled,fail', [(False, False), (True, False), (True, True)])
def test_thumbnail_client_lifecycle_budget_and_candidates(tmp_path, monkeypatch, enabled, fail):
    job = planning_job(tmp_path)
    job['options'].update(social=True, gemini_image=enabled, provider='local')
    source = tmp_path / 'output.mp4'
    source.write_bytes(b'fixture')
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    image_client = Mock()
    factory = Mock(return_value=image_client)
    monkeypatch.setattr('services.gemini_client.GeminiVideoClient', factory)
    pipeline = Pipeline()
    def build(export, clips, plan, game, *, client, job):
        assert client is (image_client if enabled else None)
        assert job['dir'] == str(tmp_path)
        if enabled:
            assert Path(client.budget.path) == tmp_path / 'gemini-budget.sqlite3'
        if fail:
            raise RuntimeError('mock build failure')
        kit = scratch / 'kit'
        kit.mkdir()
        (kit / 'chapters.txt').write_text('00:00 save')
        (kit / 'metadata.json').write_text(json.dumps({'platforms': {'youtube': {'titles': ['SAVE'], 'description': 'Save'}},
            'thumbnails': {}, 'thumbnail_candidates': [dict(provider='local', variants={'landscape': {'file': f'{i}.jpg'}}) for i in (1, 2)]}))
        return kit
    monkeypatch.setattr(pipeline, 'hook', lambda *args: build)
    token = RUNTIME_KEY.set('runtime-test-key')
    try:
        if fail:
            with pytest.raises(RuntimeError):
                finish_output(pipeline, job, source, {}, scratch)
        else:
            finish_output(pipeline, job, source, {}, scratch)
            assert len(job['share_kit']['covers']) == 2
    finally:
        RUNTIME_KEY.reset(token)
    if enabled:
        factory.assert_called_once_with(api_key='runtime-test-key')
        image_client.close.assert_called_once()
    else:
        factory.assert_not_called()
