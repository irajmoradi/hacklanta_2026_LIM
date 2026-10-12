"""Explicit live smoke, stock HTTP API, at most three generation attempts total.

Run only with LIM_FIX4_LIVE=1 and runtime credentials. Outputs live outside git.
Restarting resumes the same job and its durable call ledger.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time

import httpx
from werkzeug.serving import make_server

from server.api import create_app
from services.probe import probe_video


def main():
    assert os.getenv('LIM_FIX4_LIVE') == '1', 'Explicit live authorization required'
    assert int(os.environ['MAX_GEMINI_CALLS_PER_JOB']) <= 3
    root = Path('/srv/demo_out/fix4')
    root.mkdir(parents=True, exist_ok=True)
    app = create_app(dict(WORKSPACE=str(root / 'jobs'), JOB_WORKERS=1,
                          STAGE_TIMEOUT_SECONDS=2400, API_RATE_LIMIT=3000))
    server = make_server('127.0.0.1', 8014, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = httpx.Client(base_url='http://127.0.0.1:8014', timeout=600)
    summary = {}
    try:
        marker = root / 'job-id.txt'
        if marker.exists():
            job_id = marker.read_text().strip()
        else:
            source = root / 'first-six-minutes.mp4'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i',
                '/srv/demo_in/valorant_phoenix_44k.mp4', '-t', '360', '-r', '30',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-threads', '2',
                '-c:a', 'aac', str(source)], check=True)
            with source.open('rb') as media:
                response = client.post('/api/jobs', files={'video': ('six-minutes.mp4', media, 'video/mp4')})
            response.raise_for_status()
            job_id = response.json()['id']
            marker.write_text(job_id)
        url = '/api/jobs/' + job_id
        def snapshot():
            response = client.get(url)
            response.raise_for_status()
            return response.json()
        def wait():
            deadline = time.monotonic() + 2400
            last = None
            while time.monotonic() < deadline:
                data = snapshot()
                stage = (data['status'], data.get('pipeline_stage'))
                if stage != last:
                    print(json.dumps(dict(status=stage[0], stage=stage[1])), flush=True)
                    last = stage
                if data['status'] not in ('queued', 'analyzing', 'planning', 'rendering'):
                    assert data['status'] != 'error', data.get('error')
                    return data
                time.sleep(2)
            raise TimeoutError('Live smoke job deadline exceeded')
        def calls():
            ledger = root / 'jobs' / job_id / 'gemini-budget.sqlite3'
            if not ledger.exists(): return 0
            with sqlite3.connect(ledger) as db:
                return db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
        data = snapshot()
        if 'analyze' not in data['completed']:
            response = client.post(url + '/analyze', json=dict(game='auto', planner_v2=True,
                window_scoring=True, use_signals=True, privacy_blur=True, share_kit=True,
                mode='nice', style='clean_edit', max_duration=30, captions=False, reactions=False))
            response.raise_for_status()
            data = wait()
        summary.update(job_id=job_id, duration=data['meta']['duration'], game=data.get('game'),
                       game_confidence=data.get('game_confidence'), candidates=len(data['candidates']),
                       assessed=len(data.get('window_scores', [])), clips=len(data['clips']),
                       curve_points=len(data.get('interest_curve', [])), analysis_calls=calls())
        assert len(data['interest_curve']) >= 360
        before = calls()
        for mode in ('nice', 'mean'):
            response = client.post(url + '/render', json=dict(mode=mode, preset='landscape'))
            response.raise_for_status()
            data = wait()
            assert data['status'] == 'done'
            assert isinstance(data['share_kit'], dict) and data['share_kit']['downloads']
            video = root / (mode + '.mp4')
            video.write_bytes(client.get(data['download_url']).content)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
            summary[mode] = dict(meta=probe_video(video), timings=data['timings'],
                                 share_downloads=len(data['share_kit']['downloads']))
            (root / (mode + '-status.json')).write_text(json.dumps(data, indent=2))
        assert calls() == before, 'Mode/render unexpectedly made paid calls'
        summary.update(calls=calls(), success=True)
        print(json.dumps(summary), flush=True)
    except Exception as error:
        summary.update(success=False, error_type=type(error).__name__)
        raise
    finally:
        (root / 'results.json').write_text(json.dumps(summary, indent=2))
        client.close()
        server.shutdown()
        app.extensions['job_queue'].close()


if __name__ == '__main__':
    main()
