"""EXPLICIT LIVE SMOKE: four image calls maximum; environment/stdin key only."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'full_app'))


def main():
    from pipeline import Pipeline
    from services.gemini_client import GeminiProvider
    from services.call_budget import CallBudget
    from services.probe import probe_video
    from music import pick_or_generate
    output = Path(__file__).parent / 'out'
    output.mkdir(exist_ok=True)
    key = os.environ.get('GOOGLE_API_KEY') or sys.stdin.readline().strip()
    if not key:
        raise SystemExit('Runtime GOOGLE_API_KEY required')
    budget = CallBudget(output / 'live-budget.sqlite3', limit=4)
    pipeline = Pipeline()
    def client(*args):
        provider = GeminiProvider(api_key=key, vertexai=True)
        provider.budget = budget
        return provider
    pipeline.client = client
    inputs = [
        ('valorant', '/srv/demo_out/demo02/automatic_montage_landscape.mp4', 2, 10, 'nice',
         'ABSOLUTE CINEMA: PHOENIX DIFF'),
        ('deadlock', '/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4', 120, 128, 'mean',
         'AIM NOT FOUND: DEADLOCK EDITION'),
    ]
    report = dict(model=os.getenv('GEMINI_IMAGE_MODEL', 'gemini-3.1-flash-image'), jobs=[])
    for game, source, start, end, mode, title in inputs:
        work = output / game
        work.mkdir(exist_ok=True)
        bed = pick_or_generate('energetic', 12, 8, output_dir=work)
        job = dict(id='fish-live-'+game, source=source, dir=str(work), title=title,
                   options=dict(ai_cards=True, cards=True, mode=mode, captions=False),
                   warnings=[], meta=probe_video(source),
                   clips=[dict(start_seconds=start, end_seconds=start+2, score=.9)],
                   edit_plan=dict(render_version=2, resolution=720, fps=24,
                       music=dict(path=str(bed.path), beat_sync=False),
                       segments=[dict(source_start=start, source_end=start+2),
                                 dict(source_start=end-2, source_end=end)]))
        pipeline.render(job, None)
        entry = dict(game=game, warnings=job['warnings'], output=probe_video(job['output']),
                     timeline=job['render_evidence']['timeline'], cards={})
        for role in ('intro', 'outro'):
            entry['cards'][role] = json.loads((work / 'cards' / f'{role}.json').read_text())
        report['jobs'].append(entry)
        report['live_attempts'] = 4-budget.remaining
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(dict(game=game, warnings=job['warnings'], live_attempts=report['live_attempts'])), flush=True)
    from PIL import Image, ImageOps, ImageDraw
    sheet = Image.new('RGB', (1280, 760), '#101020')
    for row, (game, *_) in enumerate(inputs):
        for col, role in enumerate(('intro', 'outro')):
            with Image.open(output / game / 'cards' / f'{role}.png') as image:
                tile = ImageOps.contain(image.convert('RGB'), (640, 350))
            sheet.paste(tile, (col*640, row*380+30))
            ImageDraw.Draw(sheet).text((col*640+12, row*380+8), f'{game} / {role}', fill='white')
    sheet.save(output / 'contact_sheet.jpg')
    if any(c['fallback'] for job in report['jobs'] for c in job['cards'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
