"""Build the 1080p demo from actual UI recordings, API outputs and telemetry."""
import csv
import json
from pathlib import Path
import subprocess
import textwrap

from PIL import Image, ImageDraw, ImageFont

OUT = Path('/srv/demo_out/demo01')
EDIT = OUT / 'edit'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def run(args):
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args], check=True)


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))


def card(name, eyebrow, title, lines, footer='LIM / STUDIO    |    EXTENSION SPRINT'):
    image = Image.new('RGB', (1920, 1080), '#101824')
    d = ImageDraw.Draw(image)
    d.rectangle((0,0,22,1080), fill='#a5f3c3')
    d.rounded_rectangle((1390,-160,2100,550),radius=180,fill='#172e38')
    d.text((100,88),eyebrow.upper(),font=ImageFont.truetype(BOLD,26),fill='#a5f3c3')
    y=166
    for line in textwrap.wrap(title, 35):
        d.text((96,y),line,font=ImageFont.truetype(BOLD,68),fill='#f7fafc');y+=90
    y+=45
    for line in lines:
        for row in textwrap.wrap(line,76):
            d.text((102,y),row,font=ImageFont.truetype(FONT,34),fill='#ccd6df');y+=52
        y+=24
    d.line((100,980,1820,980),fill='#334955',width=2)
    d.text((100,1006),footer,font=ImageFont.truetype(FONT,23),fill='#a5b4c3')
    dest=EDIT/(name+'.png');image.save(dest);return dest


def encode(inputs, graph, target, duration):
    run([*inputs,'-filter_complex_threads','1','-filter_complex',graph,
         '-map','[v]','-map','[a]','-t',str(duration),'-r','30','-c:v','libx264',
         '-threads','4','-preset','fast','-crf','20','-pix_fmt','yuv420p',
         '-c:a','aac','-ar','48000','-ac','2','-b:a','160k','-movflags','+faststart',str(target)])


def still(name, image, duration):
    target=EDIT/(name+'.mp4')
    encode(['-loop','1','-i',str(image),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo'],
           '[0:v]fps=30,format=yuv420p[v];[1:a]anull[a]',target,duration)
    return target


def title_filter(label, y=28):
    name=EDIT/('label_'+str(len(list(EDIT.glob('label_*.txt'))))+'.txt')
    name.write_text(label)
    return f'drawtext=fontfile={BOLD}:textfile={name}:expansion=none:fontsize=34:fontcolor=white:box=1:boxcolor=0x101824@0.94:boxborderw=18:x=45:y={y}'


def main():
    EDIT.mkdir(parents=True,exist_ok=True)
    analysis=json.loads((OUT/'analysis.json').read_text())
    land=json.loads((OUT/'landscape.json').read_text())
    calls=json.loads((OUT/'live_calls.json').read_text())
    counts={key:sum(c.get('signals',{}).get(key,0)>0 for c in analysis['candidates'])
            for key in sorted({k for c in analysis['candidates'] for k in c.get('signals',{})})}
    evidence={'source_seconds':analysis['meta']['duration'],'game':analysis.get('game'),
              'game_confidence':analysis.get('game_confidence'),'candidate_windows':len(analysis['candidates']),
              'gemini_scored_windows':len(analysis.get('window_scores',[])),
              'positive_signal_windows':counts,'analysis_timings':analysis['timings'],
              'landscape_timings':land['timings'],'live_calls':len(calls)}
    (OUT/'evidence.json').write_text(json.dumps(evidence,indent=2))
    with (OUT/'clip_signals.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['id','start_seconds','end_seconds','description','source','score','signals','events'])
        for c in analysis['clips']:
            writer.writerow([c.get(k,'') for k in ['id','start_seconds','end_seconds','description','source','score']]+[json.dumps(c.get(k,{})) for k in ['signals','events']])
    parts=[]
    parts.append(still('01_title',card('title','REAL GAMEPLAY / REAL API','31 minutes. One story.',
        ['Valorant / Phoenix / Lotus / 44-kill source recording',
         'A complete editing workflow, from upload to share-ready cuts.',
         'Recorded on the Extension task branch. Demo adapters disclosed.']),8))
    parts.append(still('02_new',card('new','WHAT CHANGED','More control over every cut.',
        ['Local signals + Gemini window scoring + a full-match pass.',
         'Review evidence, trim moments and change their order.',
         'Landscape + vertical exports, team reactions and a share kit.',
         'Privacy enabled. Speech captions disabled for this run.']),12))
    ui_parts=[]
    for i,scene in enumerate(json.loads((OUT/'ui_scenes.json').read_text())):
        duration=min(9,scene['end']-scene['start'])
        target=EDIT/f'03_ui_{i:02}.mp4'
        encode(['-ss',str(scene['start']),'-i',str(OUT/'ui_raw.webm'),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo'],
               f'[0:v]scale=1920:1080,fps=30,{title_filter(scene["label"],1000)}[v];[1:a]anull[a]',target,duration)
        parts.append(target)
        ui_parts.append(target)
    ui_manifest=EDIT/'ui_concat.txt';ui_manifest.write_text(''.join(f"file '{p}'\n" for p in ui_parts))
    run(['-f','concat','-safe','0','-i',str(ui_manifest),'-c','copy','-movflags','+faststart',str(OUT/'ui_walkthrough.mp4')])
    t=analysis['timings']
    parts.append(still('04_pipeline',card('pipeline','MEASURED ON THE LINUX RUNNER','What the pipeline observed.',
        [f"{len(analysis['candidates'])} candidate windows / {len(analysis.get('window_scores',[]))} Gemini-scored window / {len(calls)} live calls.",
         f"Signals: {t.get('signals',0):.1f}s   |   Window scoring: {t.get('window_scoring',0):.1f}s",
         f"Full-match analysis: {t.get('whole_video',0):.1f}s   |   Local plan: {t.get('edit_plan',0):.1f}s",
         'Positive signal windows: '+', '.join(f'{k} {v}' for k,v in counts.items())]),12))
    background=card('compare','BEFORE / AFTER','Same source. Two edits.',[],footer='OLD VERSION (LEFT)    /    EXTENSION + TEAM REACTIONS (RIGHT)')
    target=EDIT/'05_compare.mp4'
    encode(['-loop','1','-i',str(background),'-stream_loop','-1','-i','/srv/demo_in/final_v3.mp4',
            '-stream_loop','-1','-i',str(OUT/'montage_landscape.mp4')],
           '[1:v]scale=936:526,setsar=1[l];[2:v]scale=936:526,setsar=1[r];'
           '[0:v][l]overlay=16:380[b];[b][r]overlay=968:380,fps=30[v];[2:a]alimiter=limit=0.95:level=0[a]',target,24)
    parts.append(target)
    for name,file,title,lines,duration in [
        ('06_short','montage_vertical.mp4','Ready for the vertical feed.',
         ['1080 x 1920 export','Real team reaction overlays','Source gameplay audio','Conservative HUD privacy blur'],22),
        ('07_mean','montage_mean_vertical.mp4','Same plays. Mean mode.',
         ['An alternate local story plan','Iraj + Stefanny roast reactions','No additional Gemini analysis','Review humor before sharing'],18)]:
        base=Image.open(card(name,name.split('_')[1],'',[]))
        draw=ImageDraw.Draw(base)
        for i,row in enumerate(textwrap.wrap(title,23)):
            draw.text((100,175+i*80),row,font=ImageFont.truetype(BOLD,56),fill='#f7fafc')
        for i,line in enumerate(lines):
            draw.text((102,490+i*74),line,font=ImageFont.truetype(FONT,30),fill='#ccd6df')
        image=EDIT/(name+'.png');base.save(image)
        target=EDIT/(name+'.mp4')
        encode(['-loop','1','-i',str(image),'-stream_loop','-1','-i',str(OUT/file)],
               '[1:v]scale=486:864,setsar=1[s];[0:v][s]overlay=1200:106,fps=30[v];[1:a]alimiter=limit=0.95:level=0[a]',target,duration)
        parts.append(target)
    parts.append(still('08_notes',card('notes','DEMO NOTES','Evidence, with limits.',
        ['Auto detection was inconclusive; the supplied Valorant label was used.',
         'Full-match Gemini input: a compressed 640px / 2fps proxy.',
         'UI contract adapters and privacy caching live only in demo_video/.',
         'The old/new comparison illustrates editing, not an accuracy benchmark.']),9))
    parts.append(still('09_end',card('end','LIM / STUDIO','Make every play count.',
        ['Three raw montages + share kits + per-clip signal evidence.',
         'Reproduction steps, timings and pipeline issues: docs/demo.md']),8))
    manifest=EDIT/'concat.txt';manifest.write_text(''.join(f"file '{p}'\n" for p in parts))
    run(['-f','concat','-safe','0','-i',str(manifest),'-c','copy','-movflags','+faststart',str(OUT/'extension_demo.mp4')])
    duration=float(probe(OUT/'extension_demo.mp4')['format']['duration'])
    run(['-i',str(OUT/'extension_demo.mp4'),'-vf',f'fps=1/{duration/12},scale=480:270,tile=4x3',
         '-frames:v','1',str(OUT/'contact_sheet.jpg')])
    summary={name:{'duration':probe(OUT/name)['format']['duration'],
                   'bytes':(OUT/name).stat().st_size,
                   'video':[{k:s[k] for k in ('codec_name','width','height','r_frame_rate') if k in s}
                            for s in probe(OUT/name)['streams'] if s['codec_type']=='video']}
             for name in ['extension_demo.mp4','montage_landscape.mp4','montage_vertical.mp4','montage_mean_vertical.mp4']}
    (OUT/'output_manifest.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
