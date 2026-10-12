import array
import json
import math
import subprocess
from dataclasses import replace

import pytest

from reactions import ReactionSelector, apply_reaction, load_pack, render_overlay
from reactions.demo import generate_pack
from reactions.render import layout, probe


@pytest.fixture(scope='module')
def pack(tmp_path_factory):
    return load_pack(generate_pack(tmp_path_factory.mktemp('pack')))


def make_base(path, size='320x180', audio=True):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=0x303030:s={size}:r=25:d=3']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=220:duration=3:sample_rate=48000']
    subprocess.run(cmd + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)], check=True)
    return path


def frame(path, time):
    return subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(time), '-i', str(path),
                           '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                          capture_output=True, check=True).stdout


def tone(path, start, frequency):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(start), '-i', str(path),
                          '-t', '0.2', '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    samples = array.array('f', raw)
    return 2 * abs(sum(value * complex(math.cos(2*math.pi*frequency*i/48000),
                                      math.sin(2*math.pi*frequency*i/48000))
                       for i, value in enumerate(samples))) / len(samples)


def test_selection(pack):
    selector = ReactionSelector(pack, seed=4)
    a = selector.select('fail', suggested_reaction_label='sick_kill')
    b = selector.select('fail', suggested_reaction_label='sick_kill')
    assert a.label == b.label == 'sick_kill'
    assert a.id != b.id and a.speaker != b.speaker
    assert ReactionSelector(pack).select(mode='mean').label == 'roast'
    assert ReactionSelector(pack).select(suggested_reaction_label='roast').label != 'roast'
    assert ReactionSelector(pack).select(score=0.1).label == 'wholesome'
    assert ReactionSelector([]).select() is None
    single = ReactionSelector(pack[:1])
    assert single.select() is not None
    assert single.select() is None
    with pytest.raises(ValueError):
        selector.select(mode='invalid')


@pytest.mark.parametrize('change', [{'file': '../outside.mp4'}, {'duration': -1},
                                   {'duration': float('nan')}, {'label': 'unknown'},
                                   {'background': 'unknown'}, {'text': None}])
def test_invalid_pack(pack, tmp_path, change):
    (tmp_path / 'inside.mp4').write_bytes(b'placeholder')
    entry = dict(id='test', speaker='Dot', label='hype', text='beep', file='inside.mp4',
                 duration=1, background='light')
    entry.update(change)
    (tmp_path / 'pack.json').write_text(json.dumps({'clips': [entry]}))
    with pytest.raises(ValueError):
        load_pack(tmp_path)


@pytest.mark.parametrize('preset,size,width,height', [('landscape','320x180',320,180),
                                                      ('vertical','180x320',180,320)])
def test_render_timing_position_audio(pack, tmp_path, preset, size, width, height):
    base = make_base(tmp_path / 'base.mp4', size)
    out = render_overlay(base, pack[0], preset, peak_time=1, show_speaker=True)
    info = probe(out)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert (video['width'], video['height']) == (width, height)
    assert abs(float(info['format']['duration']) - 3) < .1
    assert any(s['codec_type'] == 'audio' for s in info['streams'])
    side, x, y = layout(width, height, preset)
    assert (x > width/2 and y > height/2) if preset == 'landscape' else (x < width/2 and y < height/2)
    before, during, after = [frame(out, t) for t in (.5, 1.5, 2.5)]
    point = ((y+side//2)*width + x+side//2)*3
    assert max(before[point:point+3]) - min(before[point:point+3]) < 8
    assert max(during[point:point+3]) - min(during[point:point+3]) > 60
    assert max(after[point:point+3]) - min(after[point:point+3]) < 8
    # Outside the circular mask, the original neutral background survives.
    point = (y*width + x)*3
    assert max(during[point:point+3]) - min(during[point:point+3]) < 12
    # Inside the circular crop but outside the avatar: white has been keyed out.
    point = ((y+side//2)*width + x+int(side*.94))*3
    assert max(during[point:point+3]) < 100
    # Pop-in and pop-out are visibly less opaque than the settled avatar.
    center = ((y+side//2)*width + x+side//2)*3
    settled = max(during[center:center+3]) - min(during[center:center+3])
    for time in (1.04, 1.96):
        transition = frame(out, time)[center:center+3]
        assert max(transition) - min(transition) < settled * .8
    assert tone(out, 1.4, 220) < tone(out, .4, 220) * .4
    assert tone(out, 2.4, 220) > tone(out, .4, 220) * .8
    assert tone(out, 1.4, 880) > .04
    assert tone(out, .4, 880) < .01


def test_silent_inputs_and_boundary(pack, tmp_path):
    base = make_base(tmp_path / 'silent.mp4', audio=False)
    out = render_overlay(base, pack[0], peak_time=100)
    assert tone(out, 2.4, 880) > .04
    silent_reaction = replace(pack[0], file=base, duration=.5, background='opaque')
    audible_base = make_base(tmp_path / 'audible.mp4')
    out = render_overlay(audible_base, silent_reaction, peak_time=-1)
    assert tone(out, .2, 220) > .08  # No voice means no ducking.
    with pytest.raises(ValueError):
        render_overlay(base, pack[0], output_path=base)


def test_hook(pack, tmp_path):
    base = make_base(tmp_path / 'base.mp4')
    selector = ReactionSelector(pack)
    assert apply_reaction(base, {}, selector) == base
    assert selector.last_id is None
    result = apply_reaction(base, {'peak_time': 1, 'suggested_reaction_label': 'sick_kill'},
                            selector, enabled=True)
    assert result.exists() and result != base
    assert apply_reaction(base, {}, ReactionSelector([]), enabled=True) == base


def test_short_segment_and_existing_output(pack, tmp_path):
    original = make_base(tmp_path / 'base.mp4')
    short = tmp_path / 'short.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(original), '-t', '0.4',
                    '-c:v', 'libx264', '-c:a', 'aac', str(short)], check=True)
    output = render_overlay(short, pack[0], peak_time=4)
    assert abs(float(probe(output)['format']['duration']) - .4) < .1
    prior = output.read_bytes()
    with pytest.raises(RuntimeError):
        render_overlay(short, pack[0], output_path=output)
    assert output.read_bytes() == prior
