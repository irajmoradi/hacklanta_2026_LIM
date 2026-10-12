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
from render_saved import discord_copy
from pipeline import Pipeline
from pipeline.extensions import planner_plan
from services.fx_planning import restack_saved_job
from fx.catalog import catalog


def no_network(*args, **kwargs):
    raise RuntimeError('FX-3 saved-evidence rendering forbids network calls')


def main():
    socket.socket.connect = no_network
    socket.create_connection = no_network
    saved, out = Path('/srv/demo_out/demo02'), Path('/srv/demo_out/fx3')
    out.mkdir(parents=True, exist_ok=True)
    source = next((saved/'jobs').glob('*/source.mp4'))
    manifest = {}
    rows = ['# FX-3 per-clip effects', '', 'Privacy off. Seed 2026. Zero live calls.', '',
            '| Montage / clip | Source | Hit | VFX (output start + duration) | SFX |',
            '|---|---|---|---|---|']
    for name, duration in [('mean_vertical', 30), ('landscape', 60)]:
        saved_path = saved/f'planned_{name}.json'
        job = json.loads(saved_path.read_text())
        job['options'].update(mode='mean', privacy=False, social=False, reactions=False,
                              perf=True, captions=False, full_experience=False,
                              narration=False, audio_ai=False, max_duration=duration)
        # The saved mean vertical is only 20s. Replan its reviewed keep-list to 30s
        # locally; landscape keeps all saved cuts. No footage analysis is performed.
        if job['planner_plan']['duration'] != duration:
            planner_plan(Pipeline(), job)
        job['planner_plan']['mode'] = 'mean'
        result = restack_saved_job(job, chaos=.8, seed=2026)
        assert abs(result['planner_plan']['duration']-duration) < .001
        # Existing central roast captions conflict with big word pops.
        result['planner_plan']['text'] = []
        for segment in result['edit_plan']['segments']:
            segment['texts'] = []
            segment['reactions'] = []
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
        discord = out/f'montage_{name}_discord.mp4'
        discord_copy(output, discord, duration)
        assert discord.stat().st_size < 20_000_000
        metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
        manifest[name] = dict(seconds=round(time.monotonic()-started, 2), metadata=metadata,
            bytes=output.stat().st_size, discord_bytes=discord.stat().st_size, privacy=False,
            live_calls=0, sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            saved_plan_sha256=hashlib.sha256(saved_path.read_bytes()).hexdigest(), warnings=job['warnings'])
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
        (out/'effects.md').write_text('\n'.join(rows)+'\n')
        print(name, manifest[name]['seconds'], 'seconds', flush=True)
    (out/'catalog.json').write_text(json.dumps(catalog(), indent=2))


if __name__ == '__main__':
    main()
