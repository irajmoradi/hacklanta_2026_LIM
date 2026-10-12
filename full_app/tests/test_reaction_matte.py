"""Synthetic portraits only: no models, network, faces or voices."""
import json
import subprocess
from dataclasses import replace

import cv2
import numpy as np
import pytest

from reactions import load_pack, render_overlay
from reactions.matte import LightMatte, matte_pack
from reactions.render import layout, probe
from test_reactions import make_base, frame, tone


def portrait():
    rgb = np.full((128, 128, 3), 245, np.uint8)
    cv2.ellipse(rgb, (64, 65), (32, 46), 0, 0, 360, (140, 85, 40), -1)
    cv2.rectangle(rgb, (47, 46), (80, 58), (15, 15, 15), 2)  # glasses
    cv2.rectangle(rgb, (51, 49), (59, 54), (245, 245, 245), -1)  # enclosed light lens
    cv2.line(rgb, (50, 26), (42, 8), (25, 25, 25), 2)  # fine hair
    cv2.ellipse(rgb, (64, 88), (22, 19), 0, 0, 180, (30, 30, 30), -1)  # beard
    return rgb


def test_key_preserves_details_and_stabilizes_edges():
    source = portrait()
    key = LightMatte()
    rgba = key(source)
    assert rgba[0, 0, 3] == 0
    assert rgba[50, 54, 3] == 255  # enclosed near-background color stays opaque
    assert rgba[10, 43, 3] == 255  # hair
    assert rgba[95, 64, 3] == 255  # beard
    assert np.all(rgba[rgba[..., 3] == 255, :3] == source[rgba[..., 3] == 255])
    blurred = cv2.GaussianBlur(source, (7, 7), 1.5)
    previous = key(blurred)
    changed = blurred.copy()
    changed[20:110, 30:100] = np.minimum(changed[20:110, 30:100].astype(int)+1, 255)
    raw = LightMatte()(changed)
    smooth = key(changed)
    assert np.abs(smooth[..., 3].astype(float)-previous[..., 3]).sum() < np.abs(raw[..., 3].astype(float)-previous[..., 3]).sum()
    moved = np.full_like(source, 245)
    assert key(moved)[65, 64, 3] == 0  # no trailing old head on motion
    with pytest.raises(ValueError, match='light background'):
        LightMatte()(np.zeros_like(source))


@pytest.fixture(scope='module')
def matted(tmp_path_factory):
    root = tmp_path_factory.mktemp('matte')
    cv2.imwrite(str(root/'portrait.png'), cv2.cvtColor(portrait(), cv2.COLOR_RGB2BGR))
    subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-framerate', '25', '-i', str(root/'portrait.png'),
                    '-f', 'lavfi', '-i', 'sine=frequency=880:duration=1:sample_rate=48000',
                    '-t', '1', '-threads', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', str(root/'test.mp4')], check=True)
    manifest = {'version': 1, 'custom': 'retained', 'clips': [dict(id='test', speaker='Test',
                label='hype', text='beep', file='test.mp4', duration=1, background='light')]}
    (root/'pack.json').write_text(json.dumps(manifest))
    result = matte_pack(root, qa_dir=root/'qa')
    assert result[0]['frames'] == 25
    return root


def test_pack_idempotency_and_timing(matted):
    reaction = load_pack(matted)[0]
    assert reaction.alpha_file and reaction.mask_file
    before = {p.name: p.stat().st_mtime_ns for p in matted.iterdir()}
    assert matte_pack(matted) == [{'id': 'test', 'skipped': True}]
    assert before == {p.name: p.stat().st_mtime_ns for p in matted.iterdir()}
    assert json.loads((matted/'pack.json').read_text())['custom'] == 'retained'
    for path in (reaction.file, reaction.alpha_file, reaction.mask_file):
        info = probe(path)
        assert abs(float(info['format']['duration'])-1) < .1
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        assert (video['width'], video['height']) == (128, 128)
    mask = np.frombuffer(frame(reaction.mask_file, .5), np.uint8).reshape(128, 128, 3)
    assert mask[0, 0].max() < 3
    assert mask[70, 64].min() > 250
    assert len(list((matted/'qa').glob('*.jpg'))) == 3


@pytest.mark.parametrize('preset,size,width,height', [('landscape', '320x180', 320, 180),
    ('vertical', '180x320', 180, 320), ('square', '240x240', 240, 240)])
@pytest.mark.parametrize('use_alpha', [True, False])
def test_matte_render_all_presets(matted, tmp_path, preset, size, width, height, use_alpha):
    reaction = load_pack(matted)[0]
    if not use_alpha:
        reaction = replace(reaction, alpha_file=None)
    out = render_overlay(make_base(tmp_path/'base.mp4', size), reaction, preset, peak_time=1,
                         show_speaker=True)
    info = probe(out)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert (video['width'], video['height']) == (width, height)
    assert abs(float(info['format']['duration'])-3) < .1
    side, x, y = layout(width, height, preset)
    before, during, after = [np.frombuffer(frame(out, t), np.uint8).reshape(height, width, 3)
                             for t in (.5, 1.5, 2.5)]
    center = (y+side//2, x+side//2)
    assert np.ptp(during[center]) > 35
    assert np.ptp(before[center]) < 10 and np.ptp(after[center]) < 10
    assert during[y+side//2, x+2].max() < 65  # no white box/halo
    assert tone(out, 1.4, 880) > .04  # audio comes from original, alpha video is silent
    assert tone(out, .4, 880) < .01 and tone(out, 2.4, 880) < .01
    assert tone(out, 1.4, 220) < tone(out, .4, 220)*.4


@pytest.mark.parametrize('field', ['alpha_file', 'mask_file'])
def test_matte_path_validation(tmp_path, field):
    (tmp_path/'clip.mp4').touch()
    entry = dict(id='clip', speaker='Test', label='hype', text='beep', file='clip.mp4',
                 duration=1, background='light', **{field: '../outside.mp4'})
    (tmp_path/'pack.json').write_text(json.dumps({'clips': [entry]}))
    with pytest.raises(ValueError, match='inside the pack'):
        load_pack(tmp_path)
