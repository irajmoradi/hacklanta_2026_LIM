"""Pixel-level coverage, including the alpha overlay path that hid gameplay."""
import subprocess
import numpy as np
import pytest

from fx.bold import BOLD
from render.plan import TimedEffect
from render.placements import effects_graph


def frame(names, size, color):
    w, h = size
    graph = '[0:v]null[placement_input]' + effects_graph(
        [TimedEffect(name=n, start=0, duration=1) for n in names], size, 10, 1)
    if not names:
        graph += ';[placement_input]null[v]'
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-filter_complex_threads', '1',
        '-f', 'lavfi', '-i', f'color=c={color}:s={w}x{h}:r=10:d=1',
        '-filter_complex', graph, '-map', '[v]', '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(float)


@pytest.mark.parametrize('size', [(320, 180), (180, 320)])
@pytest.mark.parametrize('names', [('damage_flash',), ('damage_pulse',), ('damage_flash', 'damage_pulse')])
def test_damage_retains_at_least_75_percent_centre_contrast(size, names):
    # Difference between white and black reveals retained source contribution,
    # independently of the chosen tint. Chroma conversion gets 3/255 tolerance.
    w, h = size
    retained = (frame(names, size, 'white') - frame(names, size, 'black')) / 255
    centre = retained[h//3:2*h//3, w//3:2*w//3]
    assert centre.min() >= .75 - 3/255
    assert centre.mean() > retained[:3, :3].mean()


@pytest.mark.parametrize('name', sorted(BOLD))
def test_every_effect_centre_coverage_and_opacity(name):
    # Measure changed coverage and lost source contrast, including the actual
    # RGBA placement path. Full-frame transformations are intentionally allowed;
    # opaque overlays have tighter per-family contracts.
    white, black = frame([name], (320, 180), 'white'), frame([name], (320, 180), 'black')
    base = frame([], (320, 180), 'white')
    region = np.s_[60:120, 106:214]
    coverage = (abs(white-base).max(axis=2)[region] > 5).mean()
    opacity = 1 - np.clip((white-black)[region]/255, 0, 1).mean()
    max_coverage, max_opacity = (1., 1.)
    if name.startswith(('damage_', 'banner_', 'clutch_bars')) or name == 'speed_lines':
        max_coverage, max_opacity = (.30, .25)
    assert coverage <= max_coverage, (name, coverage)
    assert opacity <= max_opacity + 3/255, (name, opacity)
    if name.startswith('damage_'):
        assert BOLD[name]['length'] <= .5


@pytest.mark.parametrize('size', [(320, 180), (180, 320)])
@pytest.mark.parametrize('name', [n for n in BOLD if n.startswith('banner_')])
def test_banner_changes_at_most_30_percent_of_frame_height(size, name):
    actual = frame([name], size, 'white')
    baseline = frame([], size, 'white')
    rows = (abs(actual-baseline).max(axis=2) > 5).any(axis=1)
    assert .15 < rows.mean() <= .30
    assert not rows[len(rows)//2:].any()


def test_all_bold_fills_are_local_or_translucent():
    for name, entry in BOLD.items():
        for part in entry['filter'].split(',drawbox='):
            if 't=fill' in part and 'w=iw:h=ih:' in part:
                assert '@0.10' in part, name
