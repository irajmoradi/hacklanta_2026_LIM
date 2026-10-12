"""Run from full_app on runner 1. No Gemini calls or video analysis."""
import argparse
import array
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'full_app'))
from services.fx_planning import restack_saved_job
from pipeline import Pipeline


def protect_discord(path):
    # A second, lower-bitrate AAC encode can overshoot even a safe master.
    # Measure decoded floats; repair only audio, leaving encoded video intact.
    for attempt in range(3):
        samples = array.array('f')
        samples.frombytes(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),
                                                   '-vn','-f','f32le','-']))
        peak = max(abs(s) for s in samples)
        if peak < 1:
            return
        temporary = path.with_name(path.stem+'_headroom.mp4')
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(path),'-map','0:v:0','-map','0:a:0',
                        '-c:v','copy','-af',f'volume={.8/peak}','-c:a','aac','-b:a','128k',
                        '-movflags','+faststart',str(temporary)],check=True)
        temporary.replace(path)
    raise RuntimeError('Discord audio did not meet decoded headroom check')


def discord_copy(output, discord, duration):
    bitrate = min(2200, int(18_000_000*8/duration/1000)-128)
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(output),'-vf',
                    "scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                    '-c:v','libx264','-preset','fast','-b:v',f'{bitrate}k',
                    '-maxrate',f'{bitrate}k','-bufsize',f'{bitrate*2}k','-threads','2',
                    '-c:a','aac','-b:a','128k','-movflags','+faststart',str(discord)],check=True)
    protect_discord(discord)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--saved', type=Path, default=Path('/srv/demo_out/demo02'))
    parser.add_argument('--out', type=Path, default=Path('/srv/demo_out/fx2'))
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = next((args.saved/'jobs').glob('*/source.mp4'))
    report = ['# FX-2 saved-analysis render', '', 'Seed: '+str(args.seed)+'. Live calls: 0. Cuts and privacy settings preserved.', '',
              '| Montage / clip | Source seconds | Events (output seconds) | VFX | SFX |', '|---|---|---|---|---|']
    manifest = {}
    for name in ('landscape','vertical','mean_vertical'):
        saved_path = args.saved/f'planned_{name}.json'
        job = json.loads(saved_path.read_text())
        result = restack_saved_job(job, seed=args.seed)
        (args.out/f'planned_{name}.json').write_text(json.dumps(result, indent=2))
        work = args.out/name
        work.mkdir(exist_ok=True)
        job.update(result)
        job.update(source=str(source), dir=str(work), warnings=[], timings={})
        # Keep the DEMO-02 privacy mask; optional reaction assets are environment-dependent.
        job['options'].update(social=False, reactions=False, perf=True)
        for clip in result['planner_plan']['clips']:
            cid = clip['id']
            names = lambda group: ', '.join(f"{e['name']} @{e['start']:.2f}" for e in result['planner_plan'][group] if e['clip_id']==cid)
            events = ', '.join(f'{k} @{t:.2f}' for k,t in result['events'][cid])
            report.append(f"| {name} / {cid} | {clip['source_start']:.2f}–{clip['source_end']:.2f} | {events} | {names('effects')} | {names('sfx')} |")
        started = time.monotonic()
        Pipeline().render(job, None)
        output = args.out/f'montage_{name}.mp4'
        shutil.copy2(job['output'], output)
        discord = args.out/f'montage_{name}_discord.mp4'
        duration = result['planner_plan']['duration']
        discord_copy(output, discord, duration)
        assert discord.stat().st_size < 20_000_000
        metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
        manifest[name] = dict(final_master=True, seconds=round(time.monotonic()-started,2), metadata=metadata,
                              bytes=output.stat().st_size, discord_bytes=discord.stat().st_size,
                              sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                              saved_plan_sha256=hashlib.sha256(saved_path.read_bytes()).hexdigest(), warnings=job['warnings'])
        (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2))
        (args.out/'effects.md').write_text('\n'.join(report)+'\n')
        print(name, 'complete', manifest[name]['seconds'], 'seconds', flush=True)


if __name__ == '__main__':
    main()
