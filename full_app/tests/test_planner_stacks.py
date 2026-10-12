from collections import Counter
from unittest.mock import Mock
import pytest

from fx.catalog import catalog
from models.effects import SOUND_EFFECTS, VIDEO_EFFECTS
from planner import plan_edit
from planner.stacks import repeat_cap


def clips(n=16):
    return [dict(id=str(i), start=i*12, end=i*12+10, score=i, label='lowlight' if i%2 else 'highlight',
                 signals=dict(action_time=i*12+6, kind='whiff' if i%2 else 'kill',
                              events=[dict(kind='whiff' if i%2 else 'headshot', time=i*12+6)]))
            for i in range(n)]


@pytest.mark.parametrize('mode', ['nice', 'mean'])
@pytest.mark.parametrize('chaos', [0, .35, 1])
def test_stacks_caps_adjacency_and_seed(mode, chaos):
    plan = plan_edit(clips(), mode=mode, chaos=chaos, seed=82, target_length=80, fill_target=True)
    assert plan == plan_edit(reversed(clips()), mode=mode, chaos=chaos, seed=82, target_length=80, fill_target=True)
    for group, minimum, maximum in [(plan.effects, 1, 4), (plan.sfx, 2, 5)]:
        previous, counts = set(), Counter()
        for clip in plan.clips:
            names = [s.name for s in group if s.clip_id == clip.id]
            assert minimum <= len(names) <= maximum
            assert len(names) == len(set(names))
            assert not previous.intersection(names)
            counts.update(names)
            previous = set(names)
        assert max(counts.values()) <= repeat_cap(len(plan.clips))


def test_reroll_mode_intensity_and_catalog_coverage():
    a = plan_edit(clips(), seed=12, fill_target=True)
    b = plan_edit(clips(), seed=13, fill_target=True)
    assert a.clips == b.clips
    assert a.effects != b.effects and a.sfx != b.sfx
    mean = plan_edit(clips(), mode='mean', seed=12, fill_target=True)
    assert sum(s.gain for s in mean.sfx)/len(mean.sfx) > sum(s.gain for s in a.sfx)/len(a.sfx)
    assert mean.chaos == .6 and a.chaos == .35
    tags = catalog()
    assert {v['name'] for v in tags.values() if v['kind']=='vfx'} == VIDEO_EFFECTS.keys()-{'none'}
    assert {v['name'] for v in tags.values() if v['kind']=='sfx'} == SOUND_EFFECTS.keys()-{'none'}
    assert all({'events','mood','intensity','length'} <= v.keys() for v in tags.values())
    assert all(tags['sfx:'+s.name]['mood'] == 'hype' for s in a.sfx)


def test_one_refinement_call_and_atomic_fallback():
    refiner = Mock(return_value={'effects':[{'group':'sfx','index':0,'name':'not-real','start':0}]})
    original = plan_edit(clips())
    result = plan_edit(clips(), refiner=refiner)
    assert result.effects == original.effects and result.sfx == original.sfx
    refiner.assert_called_once()
    assert 'Event anchors:' in refiner.call_args.args[0]
    assert 'Tagged inventory:' in refiner.call_args.args[0]


def test_valid_effect_refinement():
    original = plan_edit(clips(), chaos=0)
    sound = original.sfx[0]
    refiner = Mock(return_value={'effects':[dict(group='sfx', index=0, name=sound.name, start=sound.start)]})
    result = plan_edit(clips(), chaos=0, refiner=refiner)
    assert result == original


@pytest.mark.parametrize('chaos', [-1, 1.01, float('nan')])
def test_invalid_chaos(chaos):
    with pytest.raises(ValueError):
        plan_edit(clips(), chaos=chaos)
