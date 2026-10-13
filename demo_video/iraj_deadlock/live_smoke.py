"""Explicit IRAJ-DL live smoke: stock HTTP API, one durable 60-attempt ledger.

Run through launch_live.py after remote_run.sh sync. No credentials on disk.
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time

import httpx
from werkzeug.serving import make_server
from server.api import create_app

ROOT = Path('/srv/demo_out/iraj_deadlock')
SOURCE = Path('/srv/demo_in/deadlock_iraj_gfn_20261012.mp4')
EXPORTS = [('hype', 'nice', 'landscape', 60, 'hype_montage'),
           ('meme', 'mean', 'vertical', 30, 'meme_edit'),
           ('cinematic', 'nice', 'landscape', 45, 'cinematic')]


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    assert os.environ.get('IRAJ_DL_LIVE_SMOKE') == '1'
    assert int(os.environ['MAX_GEMINI_CALLS_PER_JOB']) <= 60
    ROOT.mkdir(parents=True, exist_ok=True)
    from profiles import detect_game
    game, confidence = detect_game(SOURCE)
    save(ROOT/'preflight.json', dict(game=game, confidence=confidence))
    assert game == 'deadlock', 'Fix offline detection before starting paid analysis'
    pack = Path('reaction_packs/team')
    shutil.copytree('/srv/packs/team', pack, dirs_exist_ok=True)
    os.environ['REACTION_PACK'] = str(pack.resolve())
    sam_available = importlib.util.find_spec('sam2') is not None
    os.environ['SAM_BACKEND'] = 'local' if sam_available else 'fallback'
    os.environ['SAM2_CHECKPOINT'] = '/srv/models/sam2.1_hiera_small.pt'
    save(ROOT/'runtime.json', dict(sam2_importable=sam_available, source=str(SOURCE),
                                  call_limit=60, full_experience=True))
    app = create_app(dict(WORKSPACE=str(ROOT/'jobs'), JOB_WORKERS=1,
        MAX_CONTENT_LENGTH=12*1024**3, JOB_BYTES=60*1024**3,
        OWNER_BYTES=70*1024**3, WORKSPACE_BYTES=80*1024**3,
        STAGE_TIMEOUT_SECONDS=14400, API_RATE_LIMIT=10000))
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 8021, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = httpx.Client(base_url='http://127.0.0.1:8021', timeout=1800)
    summary = json.loads((ROOT/'results.json').read_text()) if (ROOT/'results.json').exists() else {}
    summary['success'] = False
    try:
        marker = ROOT/'job-id.txt'
        if marker.exists():
            job_id = marker.read_text().strip()
        else:
            with SOURCE.open('rb') as media:
                response = client.post('/api/jobs', files={'video': ('deadlock.mp4', media, 'video/mp4')})
                response.raise_for_status()
                job_id = response.json()['id']
            marker.write_text(job_id)
        summary['job_id'] = job_id
        url = '/api/jobs/'+job_id

        def snapshot():
            return client.get(url).raise_for_status().json()

        def wait():
            deadline, last = time.monotonic()+14400, None
            while time.monotonic() < deadline:
                data = snapshot()
                save(ROOT/'latest-status.json', data)
                state = data['status'], data.get('pipeline_stage')
                if state != last:
                    print(json.dumps(dict(status=state[0], stage=state[1])), flush=True)
                    last = state
                if data['status'] not in ('queued', 'analyzing', 'planning', 'rendering'):
                    if data['status'] == 'error':
                        save(ROOT/f'error-{int(time.time())}.json', data)
                        raise RuntimeError(data.get('error'))
                    return data
                time.sleep(5)
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
            client.post(url+'/analyze', json=dict(full_experience=True, game='auto',
                ingest=True, privacy=False, mode='nice', style='hype_montage', max_duration=60,
                prompt='Find genuine combat highlights and observable mistakes throughout this entire Deadlock match. '
                       'Reject shop menus, item purchases, idle traversal, loading screens and scoreboards. '
                       'Prefer complete fights with visible outcomes.')).raise_for_status()
            data = wait()
        if not (ROOT/'analysis-status.json').exists():
            save(ROOT/'analysis-status.json', data)
            save(ROOT/'analysis-calls.json', {'calls': calls()})
        reviewed_path = ROOT/'reviewed-clips.json'
        if reviewed_path.exists() and data.get('download_url') and not (ROOT/'pre-review').exists():
            previous = ROOT/'pre-review'
            previous.mkdir()
            save(previous/'status.json', data)
            (previous/'master.mp4').write_bytes(client.get(data['download_url']).raise_for_status().content)
            prior_share = previous/'share'
            prior_share.mkdir()
            for item in (data.get('share_kit') or {}).get('downloads', []):
                (prior_share/Path(item['label']).name).write_bytes(client.get(item['url']).raise_for_status().content)
        original_analysis = json.loads((ROOT/'analysis-status.json').read_text())
        count_file = ROOT/'analysis-calls.json'
        summary.update(game=data['game'], confidence=data['game_confidence'],
                       source_meta=data['meta'], analysis_timings=original_analysis['timings'])
        if count_file.exists():
            summary['analysis_calls'] = json.loads(count_file.read_text())['calls']
        assert data['game'] == 'deadlock', 'Auto-detection did not transfer'
        for name, mode, preset, duration, style in EXPORTS:
            if (ROOT/f'{name}-status.json').exists():
                continue
            if reviewed_path.exists():
                reviewed = json.loads(reviewed_path.read_text())
                for clip in reviewed:
                    clip['keep'] = clip['type'] == ('bad' if mode == 'mean' else 'good')
                client.patch(url+'/clips', json={'clips': reviewed}).raise_for_status()
            options = dict(full_experience=True, mode=mode, preset=preset,
                           max_duration=duration, style=style, privacy=False)
            client.post(url+'/plan', json=options).raise_for_status()
            wait()
            client.post(url+'/render', json=options).raise_for_status()
            data = wait()
            assert data['status'] == 'done'
            folder = ROOT/name
            folder.mkdir(exist_ok=True)
            with client.stream('GET', data['download_url']) as response:
                response.raise_for_status()
                with (folder/'master.mp4').open('wb') as output:
                    for block in response.iter_bytes():
                        output.write(block)
            share = folder/'share'
            share.mkdir(exist_ok=True)
            for item in (data.get('share_kit') or {}).get('downloads', []):
                response = client.get(item['url']).raise_for_status()
                (share/Path(item['label']).name).write_bytes(response.content)
            save(ROOT/f'{name}-status.json', data)
            summary[name] = dict(timings=data['timings'], warnings=data['warnings'], calls=calls())
            save(ROOT/'results.json', summary)
            print(json.dumps(dict(export=name, calls=calls())), flush=True)
        summary.update(success=True, calls=calls())
        assert calls() <= 60
    finally:
        if 'job_id' in summary:
            summary['calls'] = calls()
        save(ROOT/'results.json', summary)
        client.close()
        server.shutdown()
        app.extensions['job_queue'].close()


if __name__ == '__main__':
    main()
