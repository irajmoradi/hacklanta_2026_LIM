"""Render a mean-mode alternate through the real API without further live calls."""
import copy
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'full_app'))
from pipeline import Pipeline
from pipeline.extensions import planner_plan

OUT = Path('/srv/demo_out/demo01')


def api(route, payload=None):
    req = Request('http://127.0.0.1:8011' + route,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def main():
    job = json.loads((OUT / 'vertical.json').read_text())
    job_id = job['id']
    alternate = copy.deepcopy(job)
    analysis = json.loads((OUT / 'analysis.json').read_text())
    editorial = json.loads((ROOT / 'demo_video/editorial_selection.json').read_text())
    (OUT / 'editorial_selection.json').write_text(json.dumps(editorial, indent=2))
    edits = editorial['mean']
    lowlights = []
    for edit in edits:
        original = next(c for c in analysis['clips'] if c['start_seconds'] == edit['original_start'] and c['end_seconds'] == edit['original_end'])
        lowlights.append({**original, 'start_seconds': edit['start'], 'end_seconds': edit['end'],
                         'type': edit['type'], 'description': edit['caption'], 'caption': edit['caption'], 'editorial_review': True})
    if lowlights:
        alternate['clips'] = [*lowlights, *job['clips'][:1]]
    alternate['options'].update(mode='mean', style='meme_edit', max_duration=32)
    plan = planner_plan(Pipeline(), alternate)
    (OUT / 'mean_editorial_input.json').write_text(json.dumps(alternate, indent=2))
    # Explicit custom plan prevents mode invalidation from spending another analysis call.
    api(f'/api/jobs/{job_id}/render', dict(mode='mean', preset='vertical', edit_plan=plan,
        reactions=True, privacy=True, privacy_options={'backend': 'none', 'game': 'valorant'},
        captions=False, social=True))
    last = ''
    for _ in range(10800):
        data = api(f'/api/jobs/{job_id}')
        if data.get('pipeline_stage') != last:
            last = data.get('pipeline_stage')
            print(last, flush=True)
        if data['status'] == 'error':
            (OUT / 'mean_error.json').write_text(json.dumps(data, indent=2))
            raise RuntimeError(data['error'])
        if data['status'] == 'done':
            (OUT / 'mean_vertical.json').write_text(json.dumps(data, indent=2))
            shutil.copy2(OUT / 'jobs' / job_id / 'output.mp4', OUT / 'montage_mean_vertical.mp4')
            shutil.copytree(OUT / 'jobs' / job_id / 'share', OUT / 'share_mean_vertical', dirs_exist_ok=True)
            break
        time.sleep(1)
    else:
        raise TimeoutError('Mean render did not finish')


if __name__ == '__main__':
    main()
