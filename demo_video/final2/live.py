"""Explicit live smoke: durable allocations across all attempts, 60 total.

Alternate edits and Reroll reuse the same job through POST /plan. No store edits,
provider monkeypatches, custom plans, or imported analysis.
"""
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time

import requests
from werkzeug.serving import make_server

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'full_app'))
from server.api import create_app

ROOT = Path('/srv/demo_out/final2')
BASE = 'http://127.0.0.1:8022'
# The initial audit consumed 19 calls before two correctness fixes. Its ledger
# remains in the total. Separate final nice/mean jobs retain image budget for
# every deliverable, including Reroll, without resetting any spent ledger.
CAPS = dict(valorant=19, valorant_nice=14, valorant_mean=11, deadlock=16)


def dump(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def wait(job_id):
    previous = None
    while True:
        response = requests.get(f'{BASE}/api/jobs/{job_id}', timeout=30)
        response.raise_for_status()
        job = response.json()
        state = (job['status'], job.get('pipeline_stage'))
        if state != previous:
            print(job_id, state, flush=True)
            previous = state
        if job['status'] in ('planned', 'done', 'error', 'cancelled'):
            if job['status'] in ('error', 'cancelled'):
                dump(ROOT/f'{job_id}-error.json', job)
                raise RuntimeError(f"Job failed: {job.get('error')}")
            return job
        time.sleep(3)


def stage(job_id, name, options):
    started = time.monotonic()
    response = requests.post(f'{BASE}/api/jobs/{job_id}/{name}', json=options, timeout=60)
    response.raise_for_status()
    job = wait(job_id)
    return job, round(time.monotonic()-started, 3)


def main():
    assert os.getenv('LIM_FINAL2_LIVE') == '1'
    assert os.environ['MAX_GEMINI_CALLS_PER_JOB'] == '30'
    assert os.environ['EDITOR_AGENT_CALL_BUDGET'] == '0'
    ROOT.mkdir(exist_ok=True, parents=True)
    while not (ROOT/'source_selection.json').exists():
        time.sleep(3)
    # remote_run's worktree sync removes runner-only assets; restore at launch.
    shutil.copytree('/srv/packs/team', REPO/'full_app/reaction_packs/team', dirs_exist_ok=True)
    manifest = ROOT/'jobs.json'
    ids = json.loads(manifest.read_text()) if manifest.exists() else {}
    assert sum(CAPS.values()) == 60 and set(ids) <= CAPS.keys()
    for record, job_id in ids.items():
        ledger = ROOT/'jobs'/job_id/'gemini-budget.sqlite3'
        if ledger.exists():
            with sqlite3.connect(ledger) as db:
                assert db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0] <= CAPS[record]
    dump(ROOT/'budget_policy.json', CAPS)
    app = create_app(dict(WORKSPACE=str(ROOT/'jobs'), JOB_WORKERS=1,
        STAGE_TIMEOUT_SECONDS=14400, STAGE_MEMORY_BYTES=18*1024**3,
        API_RATE_LIMIT=100000, WORKSPACE_BYTES=80*1024**3, OWNER_BYTES=60*1024**3,
        JOB_BYTES=16*1024**3))
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 8022, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for record, game, source, variants in [
            ('valorant_nice', 'valorant', ROOT/'valorant_10min.mp4', [('nice_landscape',60,0)]),
            ('valorant_mean', 'valorant', ROOT/'valorant_10min.mp4', [('mean_vertical',30,0), ('mean_vertical_reroll',30,1)]),
            ('deadlock', 'deadlock', Path('/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4'), [('nice_landscape',45,0), ('mean_vertical',30,0)])]:
            os.environ['MAX_GEMINI_CALLS_PER_JOB'] = str(CAPS[record])
            os.environ['GEMINI_TOP_N'] = '7' if game == 'deadlock' else '4'
            if record not in ids:
                assert len(ids) < 4, 'No additional paid jobs permitted'
                started = time.monotonic()
                with source.open('rb') as video:
                    response = requests.post(BASE+'/api/jobs', files={'video': (source.name, video, 'video/mp4')}, timeout=300)
                response.raise_for_status()
                ids[record] = response.json()['id']
                dump(manifest, ids)
                dump(ROOT/f'{record}_upload.json', dict(seconds=time.monotonic()-started))
            job_id = ids[record]
            for variant, duration, seed in variants:
                destination = ROOT/f'{game}_{variant}'
                if (destination/'job.json').exists():
                    continue
                destination.mkdir(exist_ok=True)
                mean = variant.startswith('mean')
                options = dict(full_experience=True, privacy=False, fx=True, perf=True,
                    game=game, mode='mean' if mean else 'nice',
                    style='meme_edit' if mean else 'hype_montage',
                    preset='vertical' if mean else 'landscape', max_duration=duration,
                    seed=seed, chaos=.8 if mean else .6, clean=False, reaction_size='large',
                    editor_agent=False, editing_instructions='')
                current = requests.get(f'{BASE}/api/jobs/{job_id}', timeout=30).json()
                started = time.monotonic()
                job, planning = stage(job_id, 'plan' if current.get('has_clips') else 'analyze', options)
                dump(destination/'planned.json', job)
                job, rendering = stage(job_id, 'render', options)
                response = requests.get(BASE+job['download_url'], timeout=300)
                response.raise_for_status()
                (destination/'master.mp4').write_bytes(response.content)
                share = destination/'share'
                share.mkdir(exist_ok=True)
                for item in job.get('share_kit', {}).get('downloads', []):
                    response = requests.get(BASE+item['url'], timeout=300)
                    response.raise_for_status()
                    (share/Path(item['url']).name).write_bytes(response.content)
                shutil.copytree(ROOT/'jobs'/job_id/'cards', destination/'cards', dirs_exist_ok=True)
                if game == 'deadlock':
                    shutil.copyfile(ROOT/'ATTRIBUTION.txt', destination/'ATTRIBUTION.txt')
                    shutil.copyfile(ROOT/'ATTRIBUTION.txt', share/'ATTRIBUTION.txt')
                dump(destination/'timings.json', dict(analyze_or_plan=planning, render=rendering,
                    total=time.monotonic()-started, stages=job.get('timings', {})))
                dump(destination/'job.json', job)
                print('SAVED', destination.name, job.get('warnings'), flush=True)
    finally:
        used = {}
        for game, job_id in ids.items():
            ledger = ROOT/'jobs'/job_id/'gemini-budget.sqlite3'
            if ledger.exists():
                with sqlite3.connect(ledger) as db:
                    used[game] = db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
        dump(ROOT/'live_calls.json', dict(jobs=used, total=sum(used.values()), limit=60))
        server.shutdown()
        app.extensions['job_queue'].close()


if __name__ == '__main__':
    main()
