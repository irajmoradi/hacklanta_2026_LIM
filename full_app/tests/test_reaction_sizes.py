import numpy as np
import pytest

from reactions.render import layout, visible_matte


@pytest.mark.parametrize('preset,w,h,fraction', [('landscape',1920,1080,.35),
    ('vertical',1080,1920,.28), ('square',1080,1080,.32)])
@pytest.mark.parametrize('size,multiplier', [('small',.55), ('medium',.78), ('large',1)])
def test_sizes_and_bottom_corner(preset, w, h, fraction, size, multiplier):
    side, x, y = layout(w,h,preset,size)
    assert side == pytest.approx(min(w,h)*fraction*multiplier, abs=2)
    assert y+side > h
    assert (x < 0) if preset == 'vertical' else (x+side > w)


def test_matte_dust_and_faint_halo_do_not_shrink_visible_head():
    frames = np.zeros((3, 256, 256), np.uint8)
    frames[:, 45:210, 75:180] = 255
    frames[:, :5, :5] = 255  # disconnected keying dust
    frames[:, 15:30, 60:200] = 32  # faint matte leakage
    frames[2, 45:210, 180:185] = 255  # real head motion retained
    visible = visible_matte(frames)
    y,x = np.nonzero(visible)
    assert (x.min(), y.min(), x.max(), y.max()) == (75,45,184,209)
