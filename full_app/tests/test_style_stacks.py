"""Style acceptance across modes, chaos endpoints, saved restacks and render clocks."""
import pytest

from planner import plan_edit
from planner.adapter import to_render_plan
from planner.stacks_style import CLEAN_VFX, CLEAN_SFX, CINEMATIC_VFX, CINEMATIC_SFX
from fx.catalog import catalog
from services.fx_planning import restack_saved_job


def sources():
    return [dict(id=str(i), start=i*12, end=i*12+10, score=i,
                 label='lowlight' if i%2 else 'highlight', caption='BRUH missed everything',
                 signals=dict(action_time=i*12+6, kind='death' if i%2 else 'kill'))
            for i in range(18)]


@pytest.mark.parametrize('style', ['clean edit', 'cinematic', 'hype montage', 'meme edit'])
@pytest.mark.parametrize('mode', ['nice', 'mean'])
@pytest.mark.parametrize('chaos', [0, .5, 1])
def test_style_contract(style, mode, chaos):
    plan = plan_edit(sources(), style=style, mode=mode, chaos=chaos, seed=82,
                     target_length=60, fill_target=True)
    assert plan == plan_edit(reversed(sources()), style=style, mode=mode, chaos=chaos,
                             seed=82, target_length=60, fill_target=True)
    rendered = to_render_plan(plan)
    if style in ('clean edit', 'cinematic'):
        assert not plan.reactions
        assert len(plan.text) == 1 and plan.text[0].clip_id == plan.clips[-1].id
        assert plan.text[0].role == 'caption' and 'BRUH' not in plan.text[0].content
        assert not any(t.name == 'flash_white' for t in plan.transitions)
        assert not any(s['reactions'] for s in rendered['segments'])
    if style == 'clean edit':
        assert {e.name for e in plan.effects} <= CLEAN_VFX
        assert {s.name for s in plan.sfx} <= set(CLEAN_SFX)
        assert 1 <= len(plan.sfx) <= 2
        assert all(s.gain <= .25 for s in plan.sfx)
    elif style == 'cinematic':
        assert {e.name for e in plan.effects} <= CINEMATIC_VFX
        assert {s.name for s in plan.sfx} <= set(CINEMATIC_SFX)
        assert not any(s.clip_id == plan.clips[0].id for s in plan.sfx)
        assert [s.gain for s in plan.sfx] == sorted(s.gain for s in plan.sfx)
        for c in plan.clips:
            effects = [e for e in plan.effects if e.clip_id == c.id]
            assert {'vignette', 'dark_mood', 'light_grain'} <= {e.name for e in effects}
            assert all(e.duration == c.duration for e in effects)
        assert plan.music.energy_curve[0].energy < plan.music.energy_curve[-2].energy
    else:
        tags = catalog()
        for c in plan.clips:
            effects = [e for e in plan.effects if e.clip_id == c.id]
            assert sum(tags['vfx:'+e.name]['bold'] for e in effects) >= 3
            assert 2 <= len([s for s in plan.sfx if s.clip_id == c.id]) <= 5
            if style == 'meme edit' and c.label == 'lowlight':
                assert {'desaturate', 'black_and_white'} & {e.name for e in effects}
            if style == 'meme edit' and c.label == 'highlight':
                assert all(tags['vfx:'+e.name]['mood'] != 'roast' for e in effects)


@pytest.mark.parametrize('style', ['clean edit', 'cinematic'])
def test_restack_replaces_inherited_memes(style):
    plan = plan_edit(sources(), mode='mean', style='meme edit', fill_target=True)
    data = plan.model_dump()
    data['style'] = style
    result = restack_saved_job(dict(planner_plan=data), chaos=1, seed=2)
    clean = result['planner_plan']
    assert clean['clips'] == data['clips']
    assert not clean['reactions']
    assert len(clean['text']) == 1
    assert len(clean['sfx']) <= (2 if style == 'clean edit' else len(plan.clips))


@pytest.mark.parametrize('style', ['clean edit', 'cinematic'])
def test_short_and_empty_plans(style):
    assert not plan_edit([], style=style).effects
    plan = plan_edit(sources(), style=style, target_length=.5, min_clip_length=.1)
    assert plan.duration == .5
    to_render_plan(plan)
