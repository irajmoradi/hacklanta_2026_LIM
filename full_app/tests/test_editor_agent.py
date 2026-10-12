from copy import deepcopy
import json
from pathlib import Path

import pytest

from editor_agent.loop import run_agent
from editor_agent.tools import EditorTools
from services.call_budget import CallBudget


class ScriptedModel:
    def __init__(self, *calls):
        self.calls = iter(calls)
        self.feedback = []
        self.watches = 0

    def next(self, context, feedback):
        self.feedback = deepcopy(feedback)
        return next(self.calls)

    def critique(self, path):
        self.watches += 1
        return {key: 'No issue' for key in ('pacing', 'dead_air', 'repeated_kills', 'missing_context', 'reaction_timing')}


def call(tool, **args):
    return dict(tool=tool, args=args)


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_REQUEST_INTERVAL_SECONDS', '0')
    return dict(id='a'*32, dir=str(tmp_path), source=str(tmp_path/'source.mp4'),
        meta={'duration': 20}, options={'max_duration': 20},
        clips=[dict(id='kill', start_seconds=0, end_seconds=5, score=.9, signals={'kill_time': 3}, transcript='nice')],
        candidates=[], edit_plan={'render_version': 2, 'segments': [dict(source_start=0, source_end=5), dict(source_start=10, source_end=15)]})


def test_tools_and_atomic_validation(job):
    tools = EditorTools(job, job['edit_plan'])
    assert tools.execute('list_candidates', {'filter': 'kill'})[0]['score'] == .9
    assert tools.execute('inspect_window', {'t0': 1, 't1': 4})['candidates'][0]['signals']['kill_time'] == 3
    for name, args in [('trim_clip', dict(clip=0, t0=-1, t1=3)),
                       ('add_clip', dict(t0=0, t1=100)), ('remove_clip', dict(clip=100)),
                       ('reorder', dict(order=[0, 0])), ('set_music', dict(enabled=True, path='/etc/passwd')),
                       ('add_caption', dict(clip=0, text='bad', duration=6)),
                       ('add_clip', dict(t0=float('nan'), t1=3)), ('unknown', {})]:
        before = tools.snapshot()
        with pytest.raises(ValueError):
            tools.execute(name, args)
        assert tools.snapshot() == before
    tools.execute('add_caption', dict(clip=0, text='nice', start=2, duration=2))
    tools.execute('trim_clip', dict(clip=0, t0=1, t1=3))
    assert tools.plan['segments'][0]['texts'] == [dict(content='nice', start=1., duration=1.)]
    tools.execute('add_reaction', dict(clip=0, label='roast', speaker='Iraj'))
    assert tools.settings['reactions']
    tools.execute('set_music', dict(enabled=True))
    tools.execute('set_transition', dict(name='whip'))
    tools.execute('reorder', dict(order=[1, 0]))
    tools.execute('add_clip', dict(t0=16, t1=18))
    tools.execute('remove_clip', dict(clip=2))
    tools.execute('finish', dict(summary='Done'))
    assert tools.finished and tools.settings['music']


def test_model_feedback_trace_and_finish(job):
    model = ScriptedModel(call('trim_clip', clip=7, t0=1, t1=4),
                          call('trim_clip', clip=0, t0=1, t1=4, rationale='Cut quiet setup'),
                          call('finish', summary='Tighter opening'))
    events = []
    result = run_agent(job, 'Tighten opening', model, emit=events.append)
    assert not result['fallback']
    assert result['plan']['segments'][0]['source_start'] == 1
    assert model.feedback[0]['result']['error'] == 'Unknown clip index'
    assert events == result['trace']
    assert events[1]['diff']['plan']['before'] != events[1]['diff']['plan']['after']
    assert job['edit_plan']['segments'][0]['source_start'] == 0


def test_persistent_budget_and_fallback(job):
    before = deepcopy(job['edit_plan'])
    result = run_agent(job, 'shorter', ScriptedModel(call('remove_clip', clip=1)), call_limit=1)
    assert result['fallback'] and result['reason'] == 'budget_exhausted'
    assert result['plan'] == before
    result = run_agent(job, 'retry', ScriptedModel(), call_limit=1)
    assert result['calls_remaining'] == 0 and result['trace'] == []
    assert CallBudget(Path(job['dir'])/'gemini-budget.sqlite3', limit=1).remaining == 0


def test_watch_once_and_stale_preview(job):
    model = ScriptedModel(call('render_preview'), call('watch_preview'), call('watch_preview'),
                          call('trim_clip', clip=0, t0=1, t1=4), call('watch_preview'), call('finish', summary='OK'))
    rendered = []
    def preview(plan, settings):
        rendered.append(deepcopy(plan))
        return Path('preview.mp4')
    result = run_agent(job, 'Review', model, preview=preview)
    assert model.watches == 1 and len(rendered) == 1
    assert result['calls_remaining'] == 5  # six decisions and one critique
    assert result['trace'][4]['error'] == 'Render the current plan before watching it'


def test_failure_and_step_limit_keep_original(job):
    class Failure:
        def next(self, *_):
            raise RuntimeError('secret-api-key')
    result = run_agent(job, 'Review', Failure())
    assert result['fallback'] and 'secret' not in json.dumps(result)
    result = run_agent(job, 'Review', ScriptedModel(call('remove_clip', clip=1)), max_steps=1)
    assert result['reason'] == 'step_limit' and result['plan'] == job['edit_plan']
    result = run_agent(job, 'Review', ScriptedModel(), cancelled=lambda: True)
    assert result['reason'] == 'cancelled'


def test_proxy_render_synthetic(job, video):
    from editor_agent.preview import render_preview
    from perf.media import probe
    job['source'] = str(video)
    job['meta']['duration'] = 6
    plan = dict(render_version=2, segments=[dict(source_start=0, source_end=1), dict(source_start=3, source_end=4)],
                captions={'enabled': True}, transition='cut')
    plan['segments'][0]['texts'] = [dict(start=0, duration=.8, content='Synthetic gameplay')]
    path = render_preview(job, plan, dict(music=False, reactions=False))
    info = probe(path)
    assert abs(float(info['format']['duration'])-2) < .2
    stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert stream['height'] == 360


def test_critique_cannot_exceed_budget(job):
    model = ScriptedModel(call('render_preview'), call('watch_preview'))
    result = run_agent(job, 'review', model, call_limit=2, preview=lambda *_: Path('preview.mp4'))
    assert result['fallback'] and result['calls_remaining'] == 0
    assert model.watches == 0
    assert result['trace'][-1]['tool'] == 'watch_preview'
    assert result['trace'][-1]['error']


def test_budget_includes_existing_analysis_calls(job):
    budget = CallBudget(Path(job['dir'])/'gemini-budget.sqlite3', limit=12)
    for _ in range(11):
        budget.reserve()
    result = run_agent(job, 'review', ScriptedModel(call('finish', summary='Keep the draft')))
    assert not result['fallback'] and result['calls_remaining'] == 0


def test_new_plan_from_planner_and_legacy_fallback(job):
    job['edit_plan'] = None
    job['options'].update(planner=True, style='clean_edit', max_duration=10)
    result = run_agent(job, 'review', ScriptedModel(call('finish', summary='Good')))
    assert not result['fallback'] and result['plan']['render_version'] == 2
    job['edit_plan'] = dict(segments=[dict(source_start=0, source_end=4, transition_in='fade_in')])
    result = run_agent(job, 'review', ScriptedModel())
    assert result['fallback'] and result['plan'] == job['edit_plan']


def test_cancel_during_model_does_not_execute_tool(job):
    cancelled = [False]
    class Cancel:
        def next(self, context, feedback):
            assert context['calls_remaining'] == 11 and context['steps_remaining'] == 16
            cancelled[0] = True
            return call('render_preview')
    def no_preview(*_):
        pytest.fail('Must not render after cancellation')
    result = run_agent(job, 'review', Cancel(), cancelled=lambda: cancelled[0], preview=no_preview)
    assert result['reason'] == 'cancelled'


def test_critique_cache_survives_chat_requests(job):
    artifact = Path(job['dir'])/'preview.mp4'
    artifact.write_bytes(b'fake proxy for scripted model')
    def review():
        return ScriptedModel(call('render_preview'), call('watch_preview'), call('finish', summary='Reviewed'))
    first, second = review(), review()
    run_agent(job, 'review', first, preview=lambda *_: artifact)
    result = run_agent(job, 'review again', second, preview=lambda *_: artifact)
    assert not result['fallback'] and first.watches == 1 and second.watches == 0
    assert result['calls_remaining'] == 5


def test_speed_adjusted_duration_limit_and_current_preset(job):
    job['options'].update(max_duration=10, preset='vertical')
    job['edit_plan'] = dict(render_version=2, preset='landscape',
        segments=[dict(source_start=0, source_end=5, speed=.5)])
    tools = EditorTools(job, job['edit_plan'])
    tools.validate()
    before = tools.snapshot()
    with pytest.raises(ValueError, match='max_duration'):
        tools.execute('add_clip', dict(t0=10, t1=11))
    assert tools.snapshot() == before
    result = run_agent(job, 'review', ScriptedModel(call('finish', summary='Keep this cut')))
    assert not result['fallback'] and result['plan']['preset'] == 'vertical'
    assert job['edit_plan']['preset'] == 'landscape'
