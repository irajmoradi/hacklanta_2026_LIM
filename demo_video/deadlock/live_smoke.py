"""Explicit authorized live smoke through the unmodified stock HTTP API.

Run via launch_live.py. One resumable job, durable <=50-call ledger. Credentials
are environment-only. Media, statuses and logs remain outside the repository.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time

import httpx
from werkzeug.serving import make_server

from server.api import create_app
from services.probe import probe_video


ROOT = Path('/srv/demo_out/deadlock')
SOURCE = Path('/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4')


def export(client, data, mode, preset):
    stock = ROOT / f'{mode}-stock.mp4'
    stock.write_bytes(client.get(data['download_url']).raise_for_status().content)
    output = ROOT / f'{mode}-{preset}.mp4'
    # Credit is burned into the distributed copies. The stock API output is
    # retained separately for review; no application renderer patch is needed.
    credit = ROOT / 'credit.txt'
    credit.write_text('Gameplay: No Copyright Gameplay (CC BY)', encoding='utf-8')
    size = 26 if preset == 'vertical' else 30
    vf = f'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile={credit}:fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=10:x=(w-tw)/2:y=h-th-40'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(stock), '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '21', '-threads', '2',
                    '-c:a', 'aac', '-movflags', '+faststart', str(output)], check=True)
    discord = ROOT / f'{mode}-{preset}-discord.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(output), '-c:v', 'libx264',
                    '-b:v', '2400k', '-maxrate', '2600k', '-bufsize', '4800k', '-threads', '2',
                    '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(discord)], check=True)
    assert discord.stat().st_size < 20_000_000
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)
    meta = probe_video(output)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(output), '-vf',
                    f'fps=9/{meta["duration"]},scale=360:-1,tile=3x3', '-frames:v', '1',
                    str(ROOT/f'{mode}-contact.jpg')], check=True)
    return dict(meta=meta, bytes=output.stat().st_size, discord_bytes=discord.stat().st_size,
                timings=data['timings'], warnings=data['warnings'],
                segments=[dict(start=s['source_start'], end=s['source_end']) for s in data['edit_plan']['segments']])


def main():
    assert os.environ.get('DEADLOCK_LIVE_SMOKE') == '1'
    assert int(os.environ['MAX_GEMINI_CALLS_PER_JOB']) <= 50
    ROOT.mkdir(parents=True, exist_ok=True)
    pack = Path('reaction_packs/team')
    shutil.copytree('/srv/packs/team', pack, dirs_exist_ok=True)
    os.environ['REACTION_PACK'] = str(pack.resolve())
    app = create_app(dict(WORKSPACE=str(ROOT/'jobs'), JOB_WORKERS=1,
                          STAGE_TIMEOUT_SECONDS=5400, API_RATE_LIMIT=10000))
    server = make_server('127.0.0.1', 8019, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = httpx.Client(base_url='http://127.0.0.1:8019', timeout=900)
    summary = {}
    try:
        marker = ROOT/'job-id.txt'
        if marker.exists():
            job_id = marker.read_text().strip()
        else:
            with SOURCE.open('rb') as media:
                job_id = client.post('/api/jobs', files={'video': ('deadlock.mp4', media, 'video/mp4')}).raise_for_status().json()['id']
            marker.write_text(job_id)
        url = '/api/jobs/'+job_id

        def snapshot():
            return client.get(url).raise_for_status().json()

        def wait():
            deadline = time.monotonic()+5400
            last = None
            while time.monotonic() < deadline:
                data = snapshot()
                state = data['status'], data.get('pipeline_stage')
                if state != last:
                    print(json.dumps(dict(status=state[0], stage=state[1])), flush=True)
                    last = state
                if data['status'] not in ('queued', 'analyzing', 'planning', 'rendering'):
                    assert data['status'] != 'error', data.get('error')
                    return data
                time.sleep(3)
            raise TimeoutError('Stock API stage deadline')

        def calls():
            ledger = ROOT/'jobs'/job_id/'gemini-budget.sqlite3'
            if not ledger.exists():
                return 0
            with sqlite3.connect(ledger) as db:
                return db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]

        data = snapshot()
        if data['status'] in ('queued', 'analyzing', 'planning', 'rendering'):
            data = wait()
        if 'analyze' not in data['completed']:
            client.post(url+'/analyze', json=dict(game='auto', planner=True, window_scoring=True,
                use_signals=True, privacy=False, mode='nice', style='hype_montage', max_duration=45,
                captions=False, reactions=True, prompt='Find genuine highlights and lowlights across the full recording.')).raise_for_status()
            data = wait()
        (ROOT/'analysis-status.json').write_text(json.dumps(data, indent=2))
        summary.update(job_id=job_id, duration=data['meta']['duration'], game=data['game'],
                       confidence=data['game_confidence'], candidates=len(data['candidates']),
                       assessed=len(data.get('window_scores', [])), clips=len(data['clips']),
                       analysis_calls=calls(), analysis_timings=dict(data['timings']))
        assert data['game'] == 'deadlock' and data['game_confidence'] >= .7
        assert data.get('window_scores'), 'Gemini window scoring did not run'
        for mode, preset, duration in [('nice', 'landscape', 45), ('mean', 'vertical', 30)]:
            client.post(url+'/plan', json=dict(mode=mode, max_duration=duration, preset=preset,
                                              privacy=False, reactions=True, planner=True)).raise_for_status()
            data = wait()
            client.post(url+'/render', json=dict(mode=mode, preset=preset, max_duration=duration,
                                                privacy=False, reactions=True)).raise_for_status()
            data = wait()
            assert data['status'] == 'done'
            (ROOT/f'{mode}-status.json').write_text(json.dumps(data, indent=2))
            summary[mode] = export(client, data, mode, preset)
            print(json.dumps(dict(mode=mode, output=summary[mode])), flush=True)
        summary.update(calls=calls(), success=True)
        assert calls() <= 50
    finally:
        (ROOT/'results.json').write_text(json.dumps(summary, indent=2))
        client.close()
        server.shutdown()
        app.extensions['job_queue'].close()


if __name__ == '__main__':
    main()
