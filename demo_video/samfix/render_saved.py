"""SAMFIX saved-analysis replay: zero Gemini calls, privacy off, local SAM2 only."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import warnings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'full_app'))
from pipeline import Pipeline
from pipeline.experience import FULL_EXPERIENCE
from render.analysis import snap_durations
from render.plan import RenderPlan
from music import pick_or_generate
from services.probe import probe_video

# Reuse the already verified Discord encoder and decoded audio headroom check.
spec = importlib.util.spec_from_file_location('fx2_demo', ROOT/'demo_video/fx2/render_saved.py')
fx2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', choices=['landscape', 'mean_vertical'])
    args = parser.parse_args()
    saved, out = Path('/srv/demo_out/demo02'), Path('/srv/demo_out/samfix')
    out.mkdir(exist_ok=True)
    os.environ.update(REACTION_PACK='/srv/packs/team', SAM_BACKEND='local',
        SAM2_CHECKPOINT='/srv/models/sam2.1_hiera_small.pt',
        SAM2_CONFIG='configs/sam2.1/sam2.1_hiera_s.yaml', SAM_TIMEOUT='120', SAM_CLIP_BUDGET='300',
        SAM_MAX_SAMPLES='4', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    manifest_path = out/'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    variants = [('landscape','nice',60,2026), ('mean_vertical','mean',30,2026)]
    for name, mode, target, seed in variants:
        if args.only and name != args.only:
            continue
        started = time.monotonic()
        work = out/name
        work.mkdir(exist_ok=True)
        job = json.loads((saved/('planned_landscape.json' if mode == 'nice' else 'planned_mean_vertical.json')).read_text())
        job.update(source=str(saved/'jobs'/job['id']/'source.mp4'), dir=str(work), warnings=[], timings={})
        job['options'].update(FULL_EXPERIENCE)
        job['options'].update(full_experience=True, privacy=False, reaction_size='large', clean=False,
            mode=mode, max_duration=target, seed=seed, chaos=.6 if mode == 'mean' else .35,
            preset='landscape' if name == 'landscape' else 'vertical', perf=True)
        # Landscape retains the entire frame; subject tracking is useful for crops.
        # Keep the known crosshair centered; saliency-driven crop moves it off target.
        job['options']['sam_reframe'] = False
        pipeline = Pipeline()
        pipeline.client = lambda *a: (_ for _ in ()).throw(AssertionError('No paid inference permitted'))
        attempts = []
        original_hook = pipeline.hook
        def hook(module, symbol, current):
            function = original_hook(module, symbol, current)
            if (module, symbol) != ('sam', 'render_effect'):
                return function
            def record(*args, **kwargs):
                kwargs['profile'] = 'valorant'  # Saved DEMO-02 footage; centered FPS crosshair.
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    result = function(*args, **kwargs)
                messages = [str(w.message) for w in caught]
                attempts.append(dict(time=kwargs['kill_time'], warnings=messages,
                                     accepted=not any('spotlight skipped' in m for m in messages)))
                print(name, 'SAM', attempts[-1], flush=True)
                for warning in caught:
                    warnings.warn(str(warning.message), warning.category)
                return result
            return record
        pipeline.hook = hook
        pipeline.plan(job, None)
        plan = job['edit_plan']
        # Account for actual frame rounding, beat trims and joins in the end card,
        # preserving all selected source ranges and the exact requested runtime.
        bed = pick_or_generate('energetic', target+5, target*.8, output_dir=work)
        plan['music'] = dict(path=str(bed.path), beats=bed.beats, duck=True, beat_sync=True)
        parsed = RenderPlan.model_validate(plan)
        fps = parsed.fps
        durations = [round(s.duration*fps)/fps for s in parsed.segments]
        overlap = max(1, round(min(parsed.transition_duration, min(durations+[1])/3)*fps))/fps
        snapped = snap_durations(durations, bed.beats, parsed.music.snap_tolerance, overlap,
                                 1-overlap, max(1/fps,2*overlap+1/fps))
        plan['outro']['duration'] = round((target-sum(round(d*fps)/fps for d in snapped)-1+
                                         overlap*(len(durations)+1))*fps)/fps
        job['_custom_plan'] = True  # Preserve the duration-compensated card.
        # Enough labels/speakers even when the saved review suggested one repeated label.
        labels = ('bruh','clutch','fail','roast','funny') if mode == 'mean' else ('sick_kill','hype','clutch','wholesome')
        for index, segment in enumerate(plan['segments']):
            segment['reactions'][0]['label'] = labels[index % len(labels)]
            length = (segment['source_end']-segment['source_start'])/segment['speed']
            length = round(snapped[index]*fps)/fps
            reaction_duration = min(2.8, length*.6)
            segment['reactions'][0].update(start=min(length*.6, length-reaction_duration), duration=reaction_duration)
        (out/f'planned_{name}.json').write_text(json.dumps(job, indent=2))
        print(name, 'rendering', len(plan['segments']), 'clips; outro', plan['outro']['duration'], flush=True)
        pipeline.render(job, None)
        output = out/f'montage_{name}.mp4'
        shutil.copy2(job['output'], output)
        metadata = probe_video(output)
        assert abs(metadata['duration']-target) < .12, metadata
        discord = out/f'montage_{name}_discord.mp4'
        fx2.discord_copy(output, discord, target)
        assert discord.stat().st_size < 20_000_000
        evidence = job['render_evidence']
        speakers = sorted({r['speaker'] for r in evidence['reactions']})
        assert len(speakers) == 4, speakers
        assert evidence['sam'], 'Local SAM targeting must be attempted'
        assert len(attempts) == len(evidence['sam'])
        for event, attempt in zip(evidence['sam'], attempts):
            event.update(attempt)
        job['samfix_attempts'] = attempts
        assert 'privacy' not in job['timings']
        (out/f'job_{name}.json').write_text(json.dumps(job, indent=2))
        qa = out/'qa'
        qa.mkdir(exist_ok=True)
        for index, reaction in enumerate(evidence['reactions']):
            timestamp = evidence['timeline'][reaction['segment']]['start'] + reaction['start'] + min(.5,reaction['duration']/2)
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(output),
                            '-frames:v','1',str(qa/f'{name}_reaction_{index}.jpg')],check=True)
        for index, spotlight in enumerate(evidence['sam']):
            timestamp = evidence['timeline'][spotlight['segment']]['start']+spotlight['time']
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(output),
                            '-frames:v','1',str(qa/f'{name}_sam_{index}.jpg')],check=True)
        manifest[name] = dict(metadata=metadata, seconds=round(time.monotonic()-started,2),
            bytes=output.stat().st_size, discord_bytes=discord.stat().st_size,
            sha256=hashlib.sha256(output.read_bytes()).hexdigest(), seed=seed, chaos=job['options']['chaos'],
            speakers=speakers, sam=evidence['sam'], warnings=job['warnings'], gemini_calls=0)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(name, 'complete', manifest[name], flush=True)


if __name__ == '__main__':
    main()
