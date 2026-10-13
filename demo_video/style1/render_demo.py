"""Re-render saved DEMO-02 evidence on runner 1; network/paid calls forbidden."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'full_app'))
sys.path.insert(0, str(ROOT/'demo_video/fx2'))
from render_saved import discord_copy, protect_discord
from pipeline import Pipeline
from pipeline.extensions import planner_plan
from services.fx_planning import restack_saved_job
from fx.catalog import catalog


def no_network(*args, **kwargs):
    raise RuntimeError('STYLE-1 saved-evidence rendering forbids network calls')


def main():
    socket.socket.connect = no_network
    socket.create_connection = no_network
    saved, out = Path('/srv/demo_out/demo02'), Path('/srv/demo_out/style1')
    out.mkdir(parents=True, exist_ok=True)
    source = next((saved/'jobs').glob('*/source.mp4'))
    manifest = {}
    rows = ['# STYLE-1 per-clip effects', '', 'Privacy off. Seed 2026. Zero live calls.', '',
            '| Montage / clip | Source | Hit | VFX (output start + duration) | SFX |',
            '|---|---|---|---|---|']
    cases = [('mean_vertical', 30, 'mean', 'meme_edit', 'mean_vertical'),
             ('landscape', 60, 'nice', 'hype_montage', 'landscape'),
             ('cinematic', 30, 'nice', 'cinematic', 'landscape'),
             ('clean', 30, 'nice', 'clean_edit', 'landscape')]
    for name, duration, mode, style, saved_name in cases:
        saved_path = saved/f'planned_{saved_name}.json'
        job = json.loads(saved_path.read_text())
        job['options'].update(mode=mode, style=style, privacy=False, social=False, reactions=False,
                              perf=True, captions=False, full_experience=False,
                              narration=False, audio_ai=False, max_duration=duration,
                              cards=False, music=False, transitions=False, fx=False)
        # Replan only the saved reviewed analysis: style controls slow motion as
        # well as stacks. No analysis, credentials or provider calls are needed.
        planner_plan(Pipeline(), job)
        result = restack_saved_job(job, chaos=.8, seed=2026)
        assert abs(result['planner_plan']['duration']-duration) < .001
        (out/f'planned_{name}.json').write_text(json.dumps(result, indent=2))
        job.update(result)
        work = out/name
        work.mkdir(exist_ok=True)
        job.update(source=str(source), dir=str(work), warnings=[], timings={})
        for clip in result['planner_plan']['clips']:
            owned = lambda group: [e for e in result['planner_plan'][group] if e['clip_id']==clip['id']]
            vfx = ', '.join(f"{e['name']} {e['start']:.2f}+{e['duration']:.2f}" for e in owned('effects'))
            sfx = ', '.join(e['name'] for e in owned('sfx'))
            rows.append(f"| {name}/{clip['id']} | {clip['source_start']:.2f}-{clip['source_end']:.2f} | {clip['peak']:.2f} | {vfx} | {sfx} |")
        started = time.monotonic()
        Pipeline().render(job, None)
        output = out/f'montage_{name}.mp4'
        shutil.copy2(job['output'], output)
        # AAC can overshoot the render limiter after decoding. Repair only the
        # exported artifact's audio, preserving the video bitstream.
        before_audio = hashlib.sha256(output.read_bytes()).hexdigest()
        protect_discord(output)
        discord = out/f'montage_{name}_discord.mp4'
        discord_copy(output, discord, duration)
        assert discord.stat().st_size < 20_000_000
        metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
        manifest[name] = dict(seconds=round(time.monotonic()-started, 2), metadata=metadata,
            bytes=output.stat().st_size, discord_bytes=discord.stat().st_size, privacy=False, style=style,
            live_calls=0, sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            audio_headroom_repaired=before_audio != hashlib.sha256(output.read_bytes()).hexdigest(),
            saved_plan_sha256=hashlib.sha256(saved_path.read_bytes()).hexdigest(), warnings=job['warnings'])
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
        (out/'effects.md').write_text('\n'.join(rows)+'\n')
        print(name, manifest[name]['seconds'], 'seconds', flush=True)
    (out/'catalog.json').write_text(json.dumps(catalog(), indent=2))


def finalize_existing():
    """Resume export QA without repeating expensive video renders."""
    socket.socket.connect = no_network
    socket.create_connection = no_network
    out = Path('/srv/demo_out/style1')
    manifest = json.loads((out/'manifest.json').read_text())
    for name, entry in manifest.items():
        output = out/f'montage_{name}.mp4'
        protect_discord(output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        if digest != entry['sha256']:
            duration = float(entry['metadata']['format']['duration'])
            discord = out/f'montage_{name}_discord.mp4'
            discord_copy(output, discord, duration)
            entry.update(sha256=digest, bytes=output.stat().st_size,
                         discord_bytes=discord.stat().st_size, audio_headroom_repaired=True,
                         metadata=json.loads(subprocess.check_output(['ffprobe','-v','error',
                             '-show_streams','-show_format','-of','json',str(output)])))
        else:
            entry.setdefault('audio_headroom_repaired', False)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    if sys.argv[1:] == ['--finalize-existing']:
        finalize_existing()
    else:
        main()
