"""FX-3 visibility contracts on output clocks and real FFmpeg frames."""
import subprocess

import pytest

from fx.bold import BOLD
from fx.catalog import catalog
from planner import plan_edit
from planner.adapter import to_render_plan
from render.plan import RenderPlan
from render.placements import effects_graph


@pytest.mark.parametrize('mode', ['nice', 'mean'])
@pytest.mark.parametrize('chaos', [0, .6, 1])
def test_visible_phases_duration_and_simultaneous_hit(mode, chaos):
    inputs = [dict(id=str(i), start=i*10, end=i*10+8, score=i,
                   label='lowlight' if i%2 else 'highlight',
                   signals=dict(action_time=i*10+7.95, clutch=i%3 == 0,
                                kind='death' if i%2 else 'kill')) for i in range(24)]
    plan = plan_edit(inputs, mode=mode, chaos=chaos, seed=17, target_length=80, fill_target=True)
    tags = catalog()
    rendered = RenderPlan.model_validate(to_render_plan(plan))
    for clip, segment in zip(plan.clips, rendered.segments):
        effects = [e for e in plan.effects if e.clip_id == clip.id and e.name != 'slow_motion']
        assert len({e.name for e in effects if tags['vfx:'+e.name]['bold']}) >= 3
        assert all(.35 <= e.duration <= clip.duration for e in effects)
        assert {'build', 'hit', 'after'} <= {tags['vfx:'+e.name]['phase'] for e in effects}
        assert sum(e.start <= clip.peak < e.start+e.duration+1e-8 for e in effects) >= 2
        assert all(clip.start <= e.start and e.start+e.duration <= clip.start+clip.duration+1e-8 for e in effects)
        assert all(.4 <= e.duration <= 1.5 for e in effects if tags['vfx:'+e.name]['phase'] == 'after')
        graph = effects_graph(segment.timed_effects, (320, 180), 30, segment.duration)
        assert graph.count('split[plain') == len(segment.timed_effects)
        for e in segment.timed_effects:
            assert f'gte(t,{e.start})*lt(t,{e.start+e.duration})' in graph


def test_each_explicit_kill_gets_confirmation():
    plan = plan_edit([dict(id='a', start=0, end=8, score=1, label='highlight',
        signals=dict(action_time=4, events=[dict(kind='kill', time=t) for t in (2,4,6)]))],
        target_length=8, max_clip_length=8, fill_target=True)
    for clip in plan.clips:
        for t in (2,4,6):
            if clip.source_start <= t < clip.source_end:
                local = clip.start+(t-clip.source_start)/clip.speed
                assert any(e.clip_id == clip.id and e.name.startswith('hitmarker_') and
                           e.start <= local < e.start+e.duration+1e-8 for e in plan.effects)


def test_bold_catalog_metadata():
    tags = catalog()
    for name in BOLD:
        e = tags['vfx:'+name]
        assert e['bold'] and e['events'] and e['mood'] in ('both', 'hype', 'roast')
        assert .35 <= e['min_visible_duration'] <= e['length'] <= 1.5
        assert .8 <= e['intensity'] <= 1
        assert e['phase'] in ('build', 'hit', 'after')


def test_freeze_precedes_hit_compositing():
    inputs = [dict(id=str(i), start=i*10, end=i*10+8, score=i, label='highlight',
                   signals=dict(action_time=i*10+4, kind='kill')) for i in range(16)]
    saw_freeze = False
    for seed in range(10):
        plan = plan_edit(inputs, seed=seed, target_length=80, fill_target=True)
        for clip in plan.clips:
            effects = [e for e in plan.effects if e.clip_id == clip.id and e.name != 'slow_motion']
            if any(e.name == 'freeze' for e in effects):
                saw_freeze = True
                assert effects[0].name == 'freeze'
                assert any(e.name.startswith('hitmarker_') for e in effects[1:])
    assert saw_freeze


@pytest.mark.parametrize('name', sorted(BOLD))
def test_effect_changes_visible_pixels_and_is_gated(name):
    # Static original footage isolates visual change, including freeze annotations.
    from render.plan import TimedEffect
    graph = '[0:v]null[placement_input]'+effects_graph(
        [TimedEffect(name=name, start=.5, duration=1)], (320,180), 10, 2)
    raw = subprocess.run(['ffmpeg','-v','error','-filter_complex_threads','1','-f','lavfi','-i',
        'testsrc2=s=320x180:r=10:d=2','-filter_complex',graph,'-map','[v]',
        '-pix_fmt','rgb24','-f','rawvideo','-'], check=True, capture_output=True).stdout
    plain = subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i',
        'testsrc2=s=320x180:r=10:d=2','-pix_fmt','rgb24','-f','rawvideo','-'])
    import numpy as np
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1,180,320,3).astype(float)
    baseline = np.frombuffer(plain, dtype=np.uint8).reshape(-1,180,320,3).astype(float)
    assert len(frames) == len(baseline)
    assert abs(frames[1]-baseline[1]).mean() < 3
    assert abs(frames[17]-baseline[17]).mean() < 3
    # At least 1% of pixels differ strongly; subtle grades alone cannot pass the planner contract.
    assert ((abs(frames[8]-baseline[8])).max(axis=2) > 30).mean() > .01
