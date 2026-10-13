"""IRAJ-DL2: replay saved plans with Iraj only, no narrator, no network."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / 'full_app'), str(REPO)]
BEFORE = Path('/srv/demo_out/iraj_deadlock')
ROOT = Path('/srv/demo_out/iraj_deadlock2')


def dump(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def forbidden(*args, **kwargs):
    raise AssertionError('IRAJ-DL2 is offline: network/provider calls forbidden')


def main():
    os.environ.update(REACTION_PACK='/srv/packs/team', SAM_BACKEND='fallback',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    from pipeline import Pipeline
    from services import gemini_client
    from pipeline import orchestrator
    socket.socket.connect = forbidden
    socket.create_connection = forbidden
    gemini_client.GeminiVideoClient = forbidden
    orchestrator.GeminiVideoClient = forbidden
    pipeline = Pipeline()
    pipeline.client = forbidden
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in ('hype', 'meme', 'cinematic'):
        directory = ROOT / name
        directory.mkdir(exist_ok=True)
        if (directory / 'job.json').exists():
            print('Already rendered', name, flush=True)
            continue
        saved = json.loads((BEFORE / f'{name}-status.json').read_text())
        job = copy.deepcopy(saved)
        job.update(dir=str(directory), source=str(BEFORE / 'jobs' / job['id'] / 'source.mp4'),
                   warnings=[], timings={})
        for key in ('narration_track', 'render_evidence', 'render_plan', 'share_kit', 'output'):
            job.pop(key, None)
        job['options'].update(narration=False, reaction_speakers=['Iraj'],
                              gemini_image=False, social=False, generate_thumbnails=False)
        # Keep saved clip choices, timing, cards and speech words. No analysis/planning.
        plan = job['edit_plan']
        plan['captions']['transcribe'] = False
        for segment, rendered in zip(plan['segments'], saved['render_plan']['segments']):
            segment['words'] = rendered.get('words', [])
        removed = []
        if name == 'cinematic':
            # Owner-specific grade: remove sustained darkening, retain color/grain/fades.
            for index, segment in enumerate(plan['segments']):
                removed.extend(dict(segment=index, effect=e) for e in segment['timed_effects']
                               if e['name'] in ('dark_mood', 'vignette'))
                segment['timed_effects'] = [e for e in segment['timed_effects']
                                            if e['name'] not in ('dark_mood', 'vignette')]
        cards = BEFORE / 'jobs' / job['id'] / 'cards'
        for role in ('intro', 'outro'):
            assert (cards / f'{role}.png').is_file() and (cards / f'{role}.json').is_file()
        shutil.copytree(cards, directory / 'cards', dirs_exist_ok=True)
        dump(directory / 'planned.json', job)
        started = time.monotonic()
        print('Rendering', name, flush=True)
        pipeline.render(job, None)
        assert 'narration' not in job['timings'] and not job.get('narration_track')
        assert {r['speaker'] for r in job['render_evidence']['reactions']} == {'Iraj'}
        shutil.copyfile(job['output'], directory / 'master.mp4')
        shutil.copytree(BEFORE / name / 'share', directory / 'share', dirs_exist_ok=True)
        # Never leave the old narrated montage inside the copied share kit.
        for video in (directory / 'share').glob('*.mp4'):
            shutil.copyfile(directory / 'master.mp4', video)
        dump(directory / 'job.json', job)
        dump(ROOT / f'{name}-status.json', job)
        dump(directory / 'provenance.json', dict(source_status=str(BEFORE / f'{name}-status.json'),
            source_status_sha256=hashlib.sha256((BEFORE / f'{name}-status.json').read_bytes()).hexdigest(),
            render_seconds=round(time.monotonic()-started, 2), new_gemini_calls=0,
            narration=False, reaction_speakers=['Iraj'], removed_grade=removed,
            thumbnails='Copied unchanged from saved share kit; posting copy describes previous edit',
            cards='Reused cached original cards', captions='Reused saved words; no transcription'))
        print('Rendered', name, flush=True)
    dump(ROOT / 'live_calls.json', dict(total=0, limit=0, network_blocked=True))


if __name__ == '__main__':
    main()
