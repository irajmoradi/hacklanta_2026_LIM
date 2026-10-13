"""Offline POLISH-1 rerenders. Saved analysis/plans/cards; zero Gemini calls."""
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from itertools import combinations

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'full_app'))
sys.path.insert(0, str(REPO))
ROOT = Path('/srv/demo_out/polish1')
BEFORE = Path('/srv/demo_out/final2')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def package(directory, job):
    from PIL import Image
    from demo_video.final2.collect import probe, sheet
    from render.text_layout import overlaps
    master, discord = directory/'master.mp4', directory/'discord.mp4'
    info = probe(master)
    duration = float(info['format']['duration'])
    assert duration <= job['options']['max_duration']+.1
    bitrate = min(2200000, int(18_500_000*8/duration)-128000)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-threads', '2', '-i', str(master),
        '-vf', "scale='if(gt(iw,ih),1280,720)':'if(gt(iw,ih),720,1280)'",
        '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', str(bitrate),
        '-maxrate', str(bitrate), '-bufsize', str(bitrate*2), '-threads', '2',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(discord)], check=True)
    assert discord.stat().st_size < 20_000_000
    for path in (master, discord):
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-threads', '2', '-i', str(path),
                        '-f', 'null', '-'], check=True)
    evidence = job['render_evidence']
    points = [(1., 'intro'), (duration-1, 'outro')]
    global_boxes = []
    for i, (segment, timing) in enumerate(zip(job['render_plan']['segments'], evidence['timeline'])):
        origin = timing['start']
        points.append((origin+timing['duration']/2, f'clip {i}'))
        for effect in segment['timed_effects']:
            points.append((origin+effect['start']+effect['duration']/2, effect['name']))
        for effect in segment['fx']:
            points.append((origin+(effect['start']+effect['end'])/2, effect['name']))
        for box in evidence['text_boxes'].get(i, evidence['text_boxes'].get(str(i), [])):
            global_boxes.append(dict(box, start=origin+box['start'], end=origin+box['end']))
    assert all(not overlaps(a, b) for a, b in combinations(global_boxes, 2))
    for r in evidence['reactions']:
        points.append((evidence['timeline'][r['segment']]['start']+r['start']+r['duration']/2,
                       'reaction '+r['speaker']))
    points.sort()
    frames = []
    for timestamp, label in points:
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-threads', '2', '-ss', str(timestamp),
            '-i', str(master), '-frames:v', '1', '-vf', 'scale=320:-2', '-f', 'image2pipe', '-vcodec', 'png', '-'])
        frames.append((Image.open(io.BytesIO(raw)).convert('RGB'), f'{timestamp:.2f}s {label}'))
    for page in range(math.ceil(len(frames)/24)):
        sheet(frames[page*24:(page+1)*24], directory/f'contact_{page+1:02}.jpg')
    for timestamp, role in ((1., 'intro'), (duration-1, 'outro')):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(timestamp), '-i', str(master),
                        '-frames:v', '1', str(directory/f'detail_{role}.png')], check=True)
    dump(directory/'review_samples.json', points)
    dump(directory/'verification.json', dict(duration=duration, cap=job['options']['max_duration'],
         discord_bytes=discord.stat().st_size, master_bytes=master.stat().st_size,
         decode_verified=True, text_boxes_disjoint=True, sampled_frames=len(points), gemini_calls=0))


def main():
    os.environ.update(REACTION_PACK='/srv/lim/lim-final2/full_app/reaction_packs/team',
        SAM_BACKEND='local', SAM2_CHECKPOINT='/srv/models/sam2.1_hiera_small.pt',
        SAM_TIMEOUT='120', SAM_CLIP_BUDGET='300', SAM_MAX_SAMPLES='4',
        OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    from pipeline import Pipeline
    from services import gemini_client
    def forbidden(*args, **kwargs):
        raise AssertionError('POLISH-1 is offline: provider construction forbidden')
    gemini_client.GeminiVideoClient = forbidden
    pipeline = Pipeline()
    pipeline.client = forbidden
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in ('valorant_nice_landscape', 'valorant_mean_vertical'):
        directory = ROOT/name
        directory.mkdir(exist_ok=True)
        job = json.loads((BEFORE/name/'job.json').read_text())
        dump(directory/'planned.json', job)
        job['source'] = str(BEFORE/'jobs'/job['id']/'source.mp4')
        job['dir'] = str(directory)
        job['warnings'], job['timings'] = [], {}
        job['options']['gemini_image'] = False  # share covers are local; cached AI cards retained
        shutil.copytree(BEFORE/name/'cards', directory/'cards', dirs_exist_ok=True)
        started = time.monotonic()
        pipeline.render(job, None)
        shutil.copyfile(job['output'], directory/'master.mp4')
        dump(directory/'job.json', job)
        dump(directory/'timings.json', dict(render_seconds=time.monotonic()-started, stages=job['timings']))
        package(directory, job)
        print('PACKAGED', name, flush=True)
    dump(ROOT/'live_calls.json', dict(total=0, limit=6, analysis_reused=True, cards_reused=True))


if __name__ == '__main__':
    main()
