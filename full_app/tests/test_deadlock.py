"""Generated HUDs only: no player names, real footage, or paid calls."""
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from profiles import detect_game, get_profile
from profiles.detection import tesseract_ocr
from profiles.hud import layout_evidence
from signals.ocr import HUDReader, classify_deadlock, deadlock_rows, regions_for
from test_game_profiles import synthetic_video
from test_fix5 import hud_frame as valorant_hud


def add_feed(frame, y=205, victim='BRAVO'):
    cv2.rectangle(frame, (70, y), (220, y+32), (215, 240, 255), -1)
    cv2.rectangle(frame, (270, y), (400, y+32), (60, 60, 235), -1)
    cv2.putText(frame, 'ALPHA', (80, y+23), cv2.FONT_HERSHEY_SIMPLEX, .65, (0,)*3, 2)
    cv2.putText(frame, victim, (280, y+23), cv2.FONT_HERSHEY_SIMPLEX, .65, (255,)*3, 2)


@pytest.fixture
def deadlock_hud():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    for x in range(320, 1600, 105):
        cv2.circle(frame, (x+35, 45), 34, (80, 150, 210), -1)
    frame[:30, 920:1010] = 0
    cv2.putText(frame, '13:29', (935, 20), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,)*3, 1)
    cv2.putText(frame, '3,836 SOULS', (28, 960), cv2.FONT_HERSHEY_SIMPLEX, .65, (180, 255, 160), 2)
    for i, color in enumerate(((0, 255, 255), (0, 140, 255), (255, 180, 0), (255, 0, 255))):
        cv2.line(frame, (1550+i*75, 750), (1580+i*75, 1020), color, 8)
    for x in (820, 920, 1020, 1120):
        cv2.circle(frame, (x, 1020), 30, (220,)*3, 3)
    add_feed(frame)
    return frame


@pytest.mark.parametrize('width', [1920, 1280, 960])
def test_real_ocr_feed_layout_and_dedup(deadlock_hud, width):
    frame = cv2.resize(deadlock_hud, (width, width*9//16))
    png = cv2.imencode('.png', frame)[1].tobytes()
    assert all(layout_evidence(png, get_profile('deadlock'), tesseract_ocr).values())
    reader = HUDReader(regions_for('deadlock'), 3)
    assert reader.executable, 'Linux runner requires Tesseract'
    events = reader.read(frame, 0)
    assert len(events) == 1
    assert events[0]['type'] == 'kill' and events[0]['attribution'] == 'unknown'
    assert reader.read(frame, 4) == []


def test_feed_moves_and_distinct_victims(deadlock_hud, monkeypatch):
    monkeypatch.setattr('signals.ocr.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=b'ALPHA BRAVO'))
    reader = HUDReader(regions_for('deadlock'), 3)
    assert len(reader.read(deadlock_hud, 0)) == 1
    deadlock_hud[195:490, :700] = 0
    add_feed(deadlock_hud, 250)
    assert reader.read(deadlock_hud, 4) == []
    assert reader.read(deadlock_hud, 8) == []
    monkeypatch.setattr('signals.ocr.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=b'ALPHA CHARLIE'))
    assert len(reader.read(deadlock_hud, 9)) == 1
    assert len(reader.read(deadlock_hud, 19)) == 1


@pytest.mark.parametrize('text,region,kind', [
    ('FRIENDLY GUARDIAN', 'banner', None), ('ENEMY WALKER', 'banner', None),
    ('Guardian destroyed', 'banner', 'objective_taken'),
    ('Urn delivered', 'banner', 'objective_taken'),
    ('Respawn in 15', 'death_banner', 'death'),
    ('Shop upgrade', 'death_banner', None), ('FLIGHT 34', 'banner', None),
    ('KILL STREAK', 'banner', 'kill'),
])
def test_keyword_outcomes(text, region, kind):
    assert classify_deadlock(text, region)[0] == kind


def test_reject_blank_partial_and_valorant(deadlock_hud, valorant_hud):
    for frame in (np.zeros_like(deadlock_hud), valorant_hud):
        assert not all(layout_evidence(cv2.imencode('.png', frame)[1].tobytes(),
                                      get_profile('deadlock'), tesseract_ocr).values())
    deadlock_hud[700:, 1500:] = 0
    assert not all(layout_evidence(cv2.imencode('.png', deadlock_hud)[1].tobytes(),
                                  get_profile('deadlock'), tesseract_ocr).values())
    assert deadlock_rows(np.zeros((290, 640, 3), np.uint8)) == []


def test_video_detection_requires_repeated_layout(deadlock_hud, tmp_path):
    image, video = tmp_path/'hud.png', tmp_path/'hud.mp4'
    cv2.imwrite(str(image), deadlock_hud)
    subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(image), '-t', '1',
                    '-r', '10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
    name, confidence = detect_game(video, sample_count=3)
    assert name == 'deadlock' and confidence >= .75
    assert detect_game(video, sample_count=1) == ('generic', 0)


@pytest.mark.parametrize('game,text,region', [('valorant', 'ACE', 'announcements'),
    ('overwatch2', 'ELIMINATED BY', 'death_banner'), ('league_of_legends', 'PENTAKILL', 'announcements')])
def test_competing_game_fixtures(synthetic_video, game, text, region):
    assert detect_game(synthetic_video(game, text, region), sample_count=3)[0] == game


def test_missing_ocr_graceful(deadlock_hud, monkeypatch):
    monkeypatch.setattr('signals.ocr.shutil.which', lambda _: None)
    with pytest.warns(RuntimeWarning, match='unavailable'):
        reader = HUDReader(regions_for('deadlock'), 3)
    assert reader.read(deadlock_hud, 0) == []


def test_souls_changes_are_weak_economy_evidence(deadlock_hud, monkeypatch):
    reader = HUDReader(regions_for('deadlock'), 3)
    def read(value, timestamp):
        monkeypatch.setattr('signals.ocr.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=str(value).encode()))
        reader.previous.clear()
        return reader.read(deadlock_hud, timestamp)
    assert read(100, 0) == []
    assert read(200, 2) == []
    events = read(650, 4)
    assert len(events) == 1 and events[0]['type'] == 'souls_gain' and events[0]['amount'] == 450
    assert read(100, 6) == []  # Spending is not a death.
    assert read(900, 20) == []  # No inference across a long OCR gap.
