"""Synthetic HUD and stock queue regressions; zero paid calls."""
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from profiles import get_profile
from profiles.detection import tesseract_ocr
from profiles.hud import layout_evidence
from signals.ocr import HUDReader, feed_text, regions_for, valorant_rows
from test_jobs import setup, video, upload, wait


@pytest.fixture
def hud_frame():
    # Synthetic substitute for the demo HUD: no footage or player names stored.
    frame = np.zeros((1080, 1920, 3), np.uint8)
    cv2.putText(frame, '1:24', (918, 59), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,)*3, 2)
    cv2.putText(frame, '100', (580, 1040), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,)*3, 2)
    for x in (780, 900, 1018, 1128):
        cv2.circle(frame, (x, 1005), 10, (255,)*3, 3)
    for x in range(90, 395, 25):
        cv2.rectangle(frame, (x, 70), (x+15, 300), (180,)*3, 2)
    add_feed(frame)
    return frame


def add_feed(frame, y=100, left='ALPHA', right='BRAVO'):
    cv2.rectangle(frame, (1400, y), (1720, y+34), (155, 185, 80), -1)
    cv2.rectangle(frame, (1721, y), (1900, y+34), (70, 70, 210), -1)
    cv2.putText(frame, left, (1430, y+24), cv2.FONT_HERSHEY_SIMPLEX, .7, (255,)*3, 2)
    cv2.putText(frame, right, (1740, y+24), cv2.FONT_HERSHEY_SIMPLEX, .7, (255,)*3, 2)
    cv2.rectangle(frame, (1630, y+10), (1690, y+16), (255,)*3, -1)


@pytest.mark.parametrize('width', [1920, 1280, 960])
def test_real_ocr_synthetic_feed_and_layout(hud_frame, width):
    frame = cv2.resize(hud_frame, (width, width*9//16))
    reader = HUDReader(regions_for('valorant'), 3)
    assert reader.executable, 'runner needs Tesseract'
    events = reader.read(frame, 0)
    assert len(events) == 1
    assert events[0]['type'] == 'kill'
    assert events[0]['attribution'] == 'unknown'
    assert reader.read(frame, 2) == []
    png = cv2.imencode('.png', frame)[1].tobytes()
    assert all(layout_evidence(png, get_profile('valorant'), tesseract_ocr).values())


def test_feed_deduplicates_sliding_rows_and_ocr_jitter(hud_frame, monkeypatch):
    monkeypatch.setattr('signals.ocr.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=b'ALPHA BRAVO'))
    reader = HUDReader(regions_for('valorant'), 3)
    assert len(reader.read(hud_frame, 0)) == 1
    shifted = hud_frame.copy()
    shifted[85:340, 1230:] = 0
    add_feed(shifted, y=145)
    monkeypatch.setattr('signals.ocr.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=b'ALPHA BRAV0'))
    assert reader.read(shifted, 4) == []
    assert reader.read(shifted, 8) == []  # persistence is not a fresh kill
    assert len(reader.read(shifted, 18)) == 1
    assert len(reader.feed_seen) == 1
    monkeypatch.setattr('signals.ocr.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=b'ALPHA CHARLIE'))
    assert len(reader.read(shifted, 19)) == 1


def test_feed_requires_paired_colored_rows(hud_frame):
    assert feed_text('oneword') is None
    assert feed_text('KILL 123') is None
    blank = np.zeros((259, 691, 3), np.uint8)
    assert valorant_rows(blank) == []
    blank[:] = (70, 70, 210)
    assert valorant_rows(blank) == []
    frame = np.zeros_like(hud_frame)
    png = cv2.imencode('.png', frame)[1].tobytes()
    assert not any(layout_evidence(png, get_profile('valorant'), lambda _: []).values())


def test_detection_samples_synthetic_video_and_abstains_on_partial_hud(hud_frame, tmp_path):
    from profiles import detect_game
    image = tmp_path / 'hud.png'
    video = tmp_path / 'hud.mp4'
    # Exercise the actual bounded ffmpeg sampling + full OCR + layout fallback.
    cv2.imwrite(str(image), hud_frame)
    subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(image), '-t', '1',
                    '-r', '10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
    name, confidence = detect_game(video, sample_count=3)
    assert name == 'valorant' and .65 <= confidence <= .98
    hud_frame[970:] = 0
    png = cv2.imencode('.png', hud_frame)[1].tobytes()
    cues = layout_evidence(png, get_profile('valorant'), tesseract_ocr)
    assert cues['timer'] and cues['minimap'] and cues['kill_feed']
    assert not cues['abilities'] and not cues['health']


def test_shorter_render_replans_without_analysis(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    url = '/api/jobs/' + job
    assert client.post(url+'/render', json={'max_duration': 60}).status_code == 202
    assert wait(app, job)['status'] == 'done'
    # Make the stored plan longer than the next target, with valid source bounds.
    store = app.extensions['job_store']
    current = store.get(job)
    current['edit_plan']['segments'] *= 20
    store.save(current)
    pipeline.calls.clear()
    assert client.post(url+'/render', json={'max_duration': 30}).status_code == 202
    result = wait(app, job)
    assert result['status'] == 'done'
    assert pipeline.calls == ['plan', 'render']
    assert result['_local_replan'] is True
    assert result['options']['max_duration'] == 30


def test_explicit_oversized_plan_still_rejected_atomically(setup, video):
    app, client, pipeline = setup
    job = upload(client, video)
    store = app.extensions['job_store']
    before = store.get(job)
    plan = {'segments': [{'source_start': 0, 'source_end': 2}]}
    response = client.post('/api/jobs/'+job+'/render', json={'max_duration': 1, 'edit_plan': plan})
    assert response.status_code == 400
    assert store.get(job) == before
    assert not pipeline.calls


@pytest.mark.parametrize('target', [30, 20, 1])
def test_stock_local_planner_clamps_shorter_render(setup, video, target):
    from pipeline import Pipeline
    from server.validation import plan_valid
    app, client, pipeline = setup
    job = upload(client, video)
    store = app.extensions['job_store']
    current = store.get(job)
    # Reuse analysis from a long match, without decoding media or a provider.
    current['meta']['duration'] = 240
    current.update(status='planned', completed=['analyze', 'plan'],
                   clips=[dict(id=str(i), start_seconds=i*20, end_seconds=i*20+12,
                               type='good', score=1, description='Play') for i in range(12)],
                   edit_plan={'segments': [dict(source_start=0, source_end=60)]})
    current['options']['max_duration'] = 60
    store.save(current)
    local = Pipeline()
    pipeline.plan = local.plan
    assert client.post('/api/jobs/'+job+'/render', json={'max_duration': target}).status_code == 202
    result = wait(app, job)
    assert result['status'] == 'done', result['error']
    assert pipeline.calls == ['render']
    plan_valid(result['edit_plan'], 240, target)
    assert result['planner_plan']['duration'] <= target
