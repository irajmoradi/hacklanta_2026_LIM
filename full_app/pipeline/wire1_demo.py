"""Re-render saved DEMO-02 analysis with zero model/API calls.

Run on runner 1: python -m pipeline.wire1_demo
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from pipeline import Pipeline
from pipeline.experience import FULL_EXPERIENCE, enrich
from services.probe import probe_video


def main():
    saved = Path('/srv/demo_out/demo02')
    output = Path('/srv/demo_out/wire1')
    output.mkdir(parents=True, exist_ok=True)
    job = json.loads((saved / 'planned_mean_vertical.json').read_text())
    source = saved / 'jobs' / job['id'] / 'source.mp4'
    if not source.is_file():
        raise FileNotFoundError(source)
    os.environ.setdefault('REACTION_PACK', '/srv/lim/lim/full_app/reaction_packs/team')
    job.update(dir=str(output), source=str(source), warnings=[], timings={})
    job['options'] = {**job['options'], **FULL_EXPERIENCE, 'full_experience': True,
                      'privacy': False, 'preset': 'vertical', 'mode': 'mean', 'max_duration': 22}
    job['edit_plan'] = enrich(job, job['edit_plan'])
    job['edit_plan']['captions']['transcribe'] = True
    pipeline = Pipeline()
    # Prohibit accidental new inference even if a future fallback is introduced.
    pipeline.client = lambda *a: (_ for _ in ()).throw(AssertionError('Saved-analysis demo must not call a model'))
    pipeline.render(job, None)
    job['output_metadata'] = probe_video(job['output'])
    (output / 'job.json').write_text(json.dumps(job, indent=2))
    (output / 'live_calls.json').write_text(json.dumps({'gemini_calls': 0, 'other_paid_calls': 0}))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', job['output'], '-vf',
        'fps=1/2,scale=180:320,tile=6x2', '-frames:v', '1', str(output / 'contact_sheet.jpg')], check=True)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.iterdir() if p.is_file() and p.suffix in ('.mp4', '.json', '.jpg')}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(dict(output=job['output_metadata'], warnings=job['warnings'],
                         reactions=job['render_evidence']['reactions'], narration=job.get('narration_track')), indent=2))


if __name__ == '__main__':
    main()
