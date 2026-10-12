"""DEMO-02 assembly reuses DEMO-01's card and encoding helpers."""
import csv
import json
from pathlib import Path
import subprocess
import assemble as a

a.OUT = OUT = Path('/srv/demo_out/demo02')
a.EDIT = EDIT = OUT / 'edit'


def main():
    EDIT.mkdir(parents=True, exist_ok=True)
    analysis = json.loads((OUT/'analysis.json').read_text())
    exports = {n: json.loads((OUT/(n+'.json')).read_text()) for n in ('landscape','vertical','mean_vertical')}
    calls = json.loads((OUT/'live_calls.json').read_text())
    windows = analysis['window_scores']
    vetoes = sum(w['player_alive'] is not True for w in windows)
    counts = {k:sum(c.get('signals',{}).get(k,0)>0 for c in analysis['candidates'])
              for k in sorted({k for c in analysis['candidates'] for k in c.get('signals',{})})}
    evidence = dict(source_seconds=analysis['meta']['duration'], game=analysis.get('game'),
        game_confidence=analysis.get('game_confidence'), candidates=len(analysis['candidates']),
        windows_scored=len(windows), vetoes=vetoes, fused_ranks=len(analysis['clips']),
        scored_ranges=[[w['start'],w['end']] for w in windows], positive_signal_windows=counts,
        calls=calls, timings={n:d['timings'] for n,d in {'analysis':analysis,**exports}.items()},
        plans={n:d.get('planner_plan') for n,d in exports.items()}, ranked_clips=analysis['clips'],
        adapters=['Serve unchanged production React build through Flask static_folder'],
        editorial_review=json.loads((OUT/'review_applied.json').read_text()),
        old_fix4=dict(source_seconds=360, scored_windows=2, calls=3, montage_seconds=8.021333))
    (OUT/'evidence.json').write_text(json.dumps(evidence,indent=2))
    with (OUT/'clip_signals.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','start','end','score','provenance','type','caption'])
        for c in analysis['clips']:
            writer.writerow([c.get(k) for k in ['id','start_seconds','end_seconds','score','score_provenance','type','description']])
    parts=[]
    parts.append(a.still('01_title',a.card('title','LIM / EXTENSION V2','31 minutes. Three cuts.',
        ['Real Valorant source. Stock upload, analysis, planning and rendering.',
         '60-second landscape / 30-second Short / 20-second mean cut.',
         'Team reactions, local signals and budgeted Gemini scoring.']),8))
    parts.append(a.still('02_fill',a.card('fill','FIXING THE EIGHT-SECOND MONTAGE','Fill the story, not dead air.',
        ['Old smoke: 8.02 seconds from a requested 30-second target.',
         'Variety is now a preference; ranked local evidence fills gaps.',
         'Event-centered trims preserve setup and aftermath.',
         'Mean mode keeps death evidence; spectator kills stay excluded.']),10))
    parts.append(a.still('ui_note',a.card('ui_note','WORKFLOW RECORDING','From upload to first export.',
        ['The UI capture shows the automatic first pass.',
         'Source review then rejected two misclassified windows and improved trims.',
         'The comparison and exports below show the reviewed final cuts.']),8))
    ui=[]
    scenes=json.loads((OUT/'ui_scenes.json').read_text())
    review=next((s for s in scenes if s['label'].startswith('Review fused')),scenes[0])
    a.run(['-ss',str(review['start']+1),'-i',str(OUT/'ui_raw.webm'),'-frames:v','1',str(OUT/'frontend.png')])
    for i,scene in enumerate(scenes):
        duration=min(5,scene['end']-scene['start'])
        dest=EDIT/f'ui_{i:02}.mp4'
        a.encode(['-ss',str(scene['start']),'-i',str(OUT/'ui_raw.webm'),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo'],
            f'[0:v]scale=1920:1080,fps=30,{a.title_filter(scene["label"],1000)}[v];[1:a]anull[a]',dest,duration)
        ui.append(dest)
    manifest=EDIT/'ui_concat.txt';manifest.write_text(''.join(f"file '{p}'\n" for p in ui))
    a.run(['-f','concat','-safe','0','-i',str(manifest),'-c','copy',str(OUT/'ui_walkthrough.mp4')])
    parts.extend(ui)
    t=analysis['timings']
    parts.append(a.still('03_evidence',a.card('evidence','ACTUAL RUN MEASUREMENTS','Every stage leaves evidence.',
        [f"{len(analysis['candidates'])} candidates / {len(windows)} scored / {vetoes} POV vetoes.",
         f"{len(analysis['clips'])} fused ranks / {calls['used']} of 80 generation attempts.",
         f"Local signals {t.get('signals',0):.1f}s / window scoring {t.get('window_scoring',0):.1f}s.",
         f"Whole-video pass {t.get('whole_video',0):.1f}s / plan {t.get('edit_plan',0):.2f}s.",
         'Unscored local fallbacks are candidates, not verified kills.']),12))
    base=a.card('compare','SAME SOURCE / DIFFERENT EDITS','Old vs. Extension v2',[],footer='OLD VERSION (LEFT) / STOCK EXTENSION + TEAM REACTIONS (RIGHT)')
    dest=OUT/'comparison.mp4'
    a.encode(['-loop','1','-i',str(base),'-stream_loop','-1','-i','/srv/demo_in/final_v3.mp4','-i',str(OUT/'montage_landscape.mp4')],
        '[1:v]scale=936:526,setsar=1[l];[2:v]scale=936:526,setsar=1[r];[0:v][l]overlay=16:380[b];[b][r]overlay=968:380,fps=30[v];[2:a]alimiter=limit=0.95:level=0[a]',dest,18)
    parts.append(dest)
    for name,title in [('vertical','30-second vertical Short'),('mean_vertical','20-second mean-mode cut')]:
        base=a.card('base_'+name,'SAME SAVED ANALYSIS',title,
            ['Real source audio + team reactions.','No new paid calls for this export.','Full montage supplied separately.'])
        # Keep portrait footage clear of the title and copy.
        dest=EDIT/(name+'.mp4')
        a.encode(['-loop','1','-i',str(base),'-i',str(OUT/('montage_'+name+'.mp4'))],
            '[1:v]scale=432:768,setsar=1[s];[0:v][s]overlay=1440:210,fps=30[v];[1:a]alimiter=limit=0.95:level=0[a]',dest,20 if name=='mean_vertical' else 15)
        parts.append(dest)
    parts.append(a.still('04_limits',a.card('limits','QUALITY / LIMITS','Review before sharing.',
        ['Window scoring covers the strongest local candidates, not every second.',
         'Death-caption recovery is heuristic; a veto alone is not a verified fail.',
         'Vertical center crop can lose peripheral action. HUD masks are partial.',
         'The old/new comparison is illustrative, not an accuracy benchmark.']),10))
    manifest=EDIT/'concat.txt';manifest.write_text(''.join(f"file '{p}'\n" for p in parts))
    output=OUT/'extension_demo_v2.mp4'
    a.run(['-f','concat','-safe','0','-i',str(manifest),'-c','copy','-movflags','+faststart',str(output)])
    duration=float(a.probe(output)['format']['duration'])
    # Budget video plus AAC at 18 MB, with buffer/container headroom below 20 MB.
    bitrate=max(100000,int(18_000_000*8/duration)-64000)
    a.run(['-i',str(output),'-vf','fps=30,scale=1280:720','-c:v','libx264',
           '-preset','fast','-threads','4','-crf','24','-maxrate',str(bitrate),
           '-bufsize',str(bitrate*2),'-r','30','-c:a','aac','-b:a','64k',
           '-movflags','+faststart',str(OUT/'extension_demo_v2_discord.mp4')])
    a.run(['-i',str(output),'-vf',f'fps=1/{duration/12},scale=480:270,tile=4x3','-frames:v','1',str(OUT/'contact_sheet.jpg')])
    files=['extension_demo_v2.mp4','extension_demo_v2_discord.mp4','montage_landscape.mp4','montage_vertical.mp4','montage_mean_vertical.mp4','ui_walkthrough.mp4','comparison.mp4']
    manifest={name:dict(bytes=(OUT/name).stat().st_size,probe=a.probe(OUT/name)) for name in files}
    (OUT/'output_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({n:dict(bytes=m['bytes'],duration=m['probe']['format']['duration']) for n,m in manifest.items()},indent=2))


if __name__=='__main__':main()
