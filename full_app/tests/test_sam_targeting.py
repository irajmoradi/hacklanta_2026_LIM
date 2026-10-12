"""No live providers: rejection rules, spatial prompts and decoded skip behavior."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from sam import Config, render_effect
from sam.backends import LocalSegmenter
from sam.effects import composite
from sam.targeting import rejection, target_prompt, target_masks, profile_crosshair
from test_sam import video, run


def mask():
    result = np.zeros((200, 320), np.uint8)
    result[80:125, 145:175] = 1
    return result


@pytest.mark.parametrize('rule', ['too small', 'too large', 'frame edge', 'HUD', 'viewmodel',
                                  'away from crosshair', 'fragmented', 'unstable IoU'])
def test_rejection_rules(rule):
    value, previous = mask(), None
    if rule == 'too small':
        value[:] = 0
        value[100, 160] = 1
    elif rule == 'too large':
        value[20:170, 40:280] = 1
    elif rule == 'frame edge':
        value[100, :160] = 1
    elif rule == 'HUD':
        value[12:100, 150:152] = 1
    elif rule == 'viewmodel':
        value[100:150, 155:165] = 1
    elif rule == 'away from crosshair':
        value = np.roll(value, -110, axis=1)
    elif rule == 'fragmented':
        value[60:75, 120:135] = 1
    else:
        previous = np.roll(value, 30, axis=1)
    assert rejection(value, previous=previous) == rule


def test_custom_hud_and_crosshair():
    assert profile_crosshair('valorant') == (.5, .5)
    assert profile_crosshair(SimpleNamespace(detection_layout={'crosshair_center': [.4, .45]})) == (.4, .45)
    assert rejection(mask()) is None
    assert rejection(mask(), hud_boxes=((.45, .4, .55, .6),)) == 'HUD'
    assert rejection(mask(), crosshair=(.2, .5)) == 'away from crosshair'
    assert rejection(mask(), previous=mask()) is None
    prompt = target_prompt((200, 320), (.4, .45))
    assert prompt.point == (128, 90)
    assert prompt.box == pytest.approx((99.2, 62, 156.8, 126))
    with pytest.raises(ValueError):
        target_prompt((200, 320), (float('nan'), .5))


def test_local_predictor_receives_point_and_small_box(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(inference_mode=nullcontext))
    model = LocalSegmenter.__new__(LocalSegmenter)
    model.predictor = Mock()
    model.predictor.predict.return_value = (np.array([mask()]), np.array([.95]), None)
    seed = target_prompt(mask().shape)
    model.segment(np.zeros((200, 320, 3), np.uint8), 'enemy', seed)
    args = model.predictor.predict.call_args.kwargs
    assert args['point_coords'].tolist() == [[160, 100]]
    assert args['point_labels'].tolist() == [1]
    assert args['box'].tolist() == list(seed.box)


def test_feather_and_slight_background_dim():
    frame = np.full((200, 320, 3), 180, np.uint8)
    result = composite(frame, mask(), 'spotlight')
    assert 150 < result[30, 30].mean() < 180
    assert np.array_equal(result[100, 160], frame[100, 160])
    assert len(np.unique(result[80, 135:185, 0])) > 4
    assert np.array_equal(composite(frame, mask()*0, 'spotlight'), frame)


def test_no_model_skips_freeze_and_preserves_duration(video, tmp_path):
    with pytest.warns(RuntimeWarning, match='spotlight skipped: model unavailable'):
        result = render_effect(video, tmp_path/'skip.mp4', 0, 2, kill_time=1,
                               effect='spotlight_freeze', config=Config())
    cap = cv2.VideoCapture(str(result))
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 24
    cap.release()


def test_event_local_sampling_rejects_unstable_sequence(video, monkeypatch):
    points = []
    def segment(self, frame, prompt, seed):
        points.append(seed)
        h, w = frame.shape[:2]
        value = np.zeros((h, w), np.uint8)
        shift = 0 if len(points) == 1 else 14
        value[int(h*.42):int(h*.60), int(w*.45)+shift:int(w*.55)+shift] = 1
        return value
    monkeypatch.setattr('sam.targeting.BoundedBackend.segment', segment)
    with pytest.warns(RuntimeWarning, match='unstable IoU'):
        clip = target_masks(video, 0, 2, 1, config=Config(backend='local'))
    assert clip.degraded and not clip.masks.any()
    assert len(points) == 2
