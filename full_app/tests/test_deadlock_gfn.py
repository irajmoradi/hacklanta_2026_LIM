"""Generated HUD patch fixtures, with no real frames or participant names."""
import cv2
import numpy as np
import pytest

from profiles import get_profile
from profiles.detection import tesseract_ocr
from profiles.hud import layout_evidence
from signals.ocr import HUDReader, regions_for
from test_deadlock import deadlock_hud


@pytest.fixture
def three_lane_hud(deadlock_hud):
    frame = deadlock_hud.copy()
    frame[:32, 900:1040] = 0
    cv2.putText(frame, '31:38', (932, 32), cv2.FONT_HERSHEY_SIMPLEX, .65, (255,)*3, 2)
    frame[910:985, :260] = 0
    cv2.putText(frame, '7,719 SOULS', (88, 885), cv2.FONT_HERSHEY_SIMPLEX, .65, (180, 255, 160), 2)
    frame[700:, 1500:] = 0
    for i, color in enumerate(((0, 140, 255), (0, 255, 0), (255, 180, 0))):
        cv2.line(frame, (1550+i*100, 700), (1580+i*100, 1020), color, 8)
    # A small stats overlay at top right must not change HUD classification.
    cv2.putText(frame, '122 FPS 21 PING', (1640, 28), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 0), 1)
    return frame


@pytest.mark.parametrize('width', [2560, 1280, 960])
def test_three_lane_layout_and_events(three_lane_hud, width):
    frame = cv2.resize(three_lane_hud, (width, width*9//16))
    png = cv2.imencode('.png', frame)[1].tobytes()
    assert all(layout_evidence(png, get_profile('deadlock'), tesseract_ocr).values())
    events = HUDReader(regions_for('deadlock'), 3).read(frame, 0)
    assert any(e['type'] == 'kill' and e['attribution'] == 'unknown' for e in events)


def test_three_lane_incomplete_hud_abstains(three_lane_hud):
    three_lane_hud[:130] = 0
    cues = layout_evidence(cv2.imencode('.png', three_lane_hud)[1].tobytes(),
                           get_profile('deadlock'), tesseract_ocr)
    assert not all(cues.values())


def test_stats_alone_are_not_a_game():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.putText(frame, '122 FPS 21 PING', (980, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 0), 1)
    assert not all(layout_evidence(cv2.imencode('.png', frame)[1].tobytes(),
                                  get_profile('deadlock'), tesseract_ocr).values())
