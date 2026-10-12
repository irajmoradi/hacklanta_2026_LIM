"""Decode the final artifacts, audit replay/feature evidence, and build QA tables."""
import array
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'full_app'))
from PIL import Image, ImageDraw
from pipeline import Pipeline
from pipeline.extensions import planner_plan
from planner.models import RankedClip, RenderPlan
from planner.stacks import events_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', choices=['landscape','vertical','mean_vertical','mean_vertical_reroll'])
    args = parser.parse_args()
    out = Path('/srv/demo_out/final')
    manifest = json.loads((out/'manifest.json').read_text())
    rows = ['# Final montage clip table', '',
            'Event times are output seconds; detector anchors and description-derived classifications are distinguished in saved analysis.', '',
            '| Montage / clip | Source seconds | Events | VFX | SFX | Speaker / line |',
            '|---|---|---|---|---|---|']
    verification = {}
    cells = []
    for name in ('landscape', 'vertical', 'mean_vertical', 'mean_vertical_reroll'):
        if args.only and name != args.only:
            continue
        job = json.loads((out/f'job_{name}.json').read_text())
        evidence = job['render_evidence']
        assert not job['options']['privacy'] and not evidence['privacy']
        assert evidence['sam'] and len({r['speaker'] for r in evidence['reactions']}) == 4
        if job['options']['mode'] == 'nice':
            assert all(not r['explicit'] for r in evidence['reactions'])
        graphs = '\n'.join(evidence['filter_graphs'])
        assert 'xfade=' in graphs and 'sidechaincompress' in graphs
        assert job['render_plan']['music']['beat_sync'] and job['render_plan']['music']['beats']
        replay = dict(options=job['options'].copy(), clips=job['clips'], game=job.get('game'))
        pipeline, sources = Pipeline(), {}
        original_hook = pipeline.hook
        def capture(module, symbol, current):
            function = original_hook(module, symbol, current)
            if (module, symbol) != ('planner', 'plan_edit'):
                return function
            def record(clips, **options):
                sources.update({c['id']: RankedClip.model_validate(c) for c in clips})
                return function(clips, **options)
            return record
        pipeline.hook = capture
        planner_plan(pipeline, replay)
        assert replay['planner_plan'] == job['planner_plan']
        native = RenderPlan.model_validate(job['planner_plan'])
        for index, segment in enumerate(job['edit_plan']['segments']):
            clip = native.clips[index]
            source = sources[clip.source_id]
            start = evidence['timeline'][index]['start']
            events = ', '.join(f'{kind} @{start+t-clip.start:.2f}' for kind,t in events_for(clip,source))
            vfx = ', '.join(f"{e['name']} @{start+e['start']:.2f}" for e in segment['timed_effects'])
            if segment['speed'] == .5:
                vfx = 'slow_motion (0.5x), ' + vfx
            sfx = ', '.join(f"{e['sfx_key']} @{start+e['offset_in_segment']:.2f}" for e in segment['sound_effects'])
            reactions = '; '.join(f"{r['speaker']}: {r['text']} ({r['label']}{', explicit' if r['explicit'] else ''})"
                                  for r in evidence['reactions'] if r['segment']==index)
            rows.append(f'| {name} / {index+1} | {clip.source_start:.2f}–{clip.source_end:.2f} | {events} | {vfx} | {sfx} | {reactions} |')
        for suffix in ('', '_discord'):
            path = out/f'montage_{name}{suffix}.mp4'
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'], check=True)
            floats = array.array('f')
            floats.frombytes(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-f','f32le','-']))
            peak = max(abs(v) for v in floats)
            assert peak < 1, (path, peak)
            if suffix:
                assert path.stat().st_size < 20_000_000
            verification[path.name] = dict(decoded=True,peak=peak,bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted((out/'qa').glob(f'{name}_reaction_*.jpg')):
            img = Image.open(path).convert('RGB')
            img.thumbnail((384,384))
            cell = Image.new('RGB',(400,420),'#161820')
            cell.paste(img,((400-img.width)//2,0))
            ImageDraw.Draw(cell).text((8,390),path.stem,fill='white')
            cells.append(cell)
    if not args.only:
        first = json.loads((out/'job_mean_vertical.json').read_text())
        second = json.loads((out/'job_mean_vertical_reroll.json').read_text())
        assert first['planner_plan']['clips'] == second['planner_plan']['clips']
        assert first['render_evidence']['timeline'] == second['render_evidence']['timeline']
        assert first['planner_plan']['effects'] != second['planner_plan']['effects']
        assert first['planner_plan']['sfx'] != second['planner_plan']['sfx']
    sheet = Image.new('RGB',(1600,420*((len(cells)+3)//4)),'#161820')
    for i,cell in enumerate(cells):
        sheet.paste(cell,((i%4)*400,(i//4)*420))
    sheet.save(out/'contact_sheet.jpg',quality=90)
    (out/'clips.md').write_text('\n'.join(rows)+'\n')
    (out/'verification.json').write_text(json.dumps(verification,indent=2))
    print(json.dumps(verification,indent=2))


if __name__ == '__main__':
    main()
