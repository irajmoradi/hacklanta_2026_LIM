import json
import subprocess

import pytest

from planner import plan_edit
from planner.adapter import to_render_plan
from render.plan import RenderPlan
from pipeline import Pipeline
from services.probe import probe_video


def planned(style='hype montage', aspect='1:1'):
    return plan_edit([dict(id='one', start=0, end=2, score=.9, label='highlight',
                          caption='Edited caption', signals=dict(clutch=True, kill_time=1))],
                     style=style, aspect=aspect, target_length=4)


def test_versioned_adapter_preserves_output_placements():
    native = planned()
    result = RenderPlan.model_validate(to_render_plan(native))
    assert result.preset == 'square'
    assert sum(s.duration for s in result.segments) == pytest.approx(native.duration)
    for c, s in zip(native.clips, result.segments):
        assert s.speed == c.speed
        assert not any(e.name == 'slow_motion' for e in s.timed_effects)
        for original, text in zip([t for t in native.text if t.clip_id == c.id], s.texts):
            assert text.start == pytest.approx(original.start-c.start)
            assert text.duration == original.duration
        for original, sound in zip([t for t in native.sfx if t.clip_id == c.id], s.sound_effects):
            assert sound.offset_in_segment == pytest.approx(original.start-c.start)
            assert sound.duration == original.duration
        for original, reaction in zip([t for t in native.reactions if t.clip_id == c.id], s.reactions):
            assert reaction.start == pytest.approx(original.start-c.start)
            assert reaction.duration == original.duration


def test_empty_and_unknown_versions_rejected():
    with pytest.raises(ValueError, match='empty'):
        to_render_plan(plan_edit([]))
    native = planned().model_dump()
    native['version'] = 3
    with pytest.raises(ValueError):
        to_render_plan(native)


@pytest.mark.parametrize('style', ['hype montage', 'clean edit', 'meme edit', 'cinematic'])
def test_native_planner_to_real_pipeline(tmp_path, monkeypatch, style):
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=s=160x90:r=20', '-f', 'lavfi', '-i', 'sine=frequency=440',
                    '-t', '2', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
    (tmp_path / 'pack.json').write_text(json.dumps({'clips': [dict(id='reaction', speaker='test',
        label='clutch', text='clutch', file='source.mp4', duration=.3, background='opaque')]}))
    monkeypatch.setenv('REACTION_PACK', str(tmp_path))
    plan = to_render_plan(planned(style))
    plan['resolution'] = 720
    job = dict(source=str(source), dir=str(tmp_path), meta=probe_video(source),
               options=dict(privacy=False, reactions=True), warnings=[], clips=[], edit_plan=plan)
    Pipeline().render(job, None)
    meta = probe_video(job['output'])
    assert (meta['width'], meta['height']) == (720, 720)
    assert meta['duration'] == pytest.approx(4, abs=.15)
    assert meta['audio_codec'] == 'aac'
    assert job['edit_plan'] == plan
    assert 'reactions_0' not in job['timings']
    assert 'reactions_1' in job['timings']
