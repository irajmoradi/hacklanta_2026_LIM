"""Offline packaging and event-by-event visual review sheets; no provider calls."""
import io
import json
import math
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw

ROOT = Path('/srv/demo_out/final2')


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format',
        '-show_streams','-of','json',str(path)]))


def sheet(items, output, columns=4):
    canvas = Image.new('RGB', (columns*320, math.ceil(len(items)/columns)*204), '#141820')
    draw = ImageDraw.Draw(canvas)
    for i, (frame, label) in enumerate(items):
        frame.thumbnail((320,180))
        x, y = (i%columns)*320, (i//columns)*204
        canvas.paste(frame, (x+(320-frame.width)//2,y+(180-frame.height)//2))
        draw.text((x+5,y+181),label[:49],fill='white')
    canvas.save(output, quality=88)


def main():
    summary = ['# FINAL-2 outputs', '', '| Cut | Seconds / cap | MB / Discord MB | Speakers | SAM | AI cards | AI thumbnail candidates |',
               '|---|---|---|---|---|---|---|']
    for directory in sorted(ROOT.glob('*_*')):
        if not (directory/'job.json').exists():
            continue
        job = json.loads((directory/'job.json').read_text())
        master = directory/'master.mp4'
        info = probe(master)
        duration = float(info['format']['duration'])
        cap = job['options']['max_duration']
        assert duration <= cap+.1, (directory.name, duration, cap)
        discord = directory/'discord.mp4'
        if not discord.exists():
            bitrate = min(2200000, int(18_500_000*8/duration)-128000)
            subprocess.run(['ffmpeg','-v','error','-y','-threads','2','-i',str(master),
                '-vf',"scale='if(gt(iw,ih),1280,720)':'if(gt(iw,ih),720,1280)'",
                '-c:v','libx264','-preset','veryfast','-b:v',str(bitrate),
                '-maxrate',str(bitrate),'-bufsize',str(bitrate*2),'-threads','2',
                '-c:a','aac','-b:a','128k','-movflags','+faststart',str(discord)],check=True)
        assert discord.stat().st_size < 20_000_000
        # Decode every delivered frame/audio packet, not just review samples.
        for media in (master, discord):
            subprocess.run(['ffmpeg','-v','error','-xerror','-threads','2','-i',str(media),
                            '-f','null','-'], check=True, capture_output=True)
        audio_streams = [s for s in info['streams'] if s['codec_type'] == 'audio']
        assert audio_streams, 'Master must contain audio'
        plan, evidence = job['render_plan'], job['render_evidence']
        points = [(min(1,duration/2), 'intro')]
        for i, (segment, timing) in enumerate(zip(plan['segments'], evidence['timeline'])):
            origin = timing['start']
            points.append((origin+timing['duration']/2, f'clip {i}'))
            for effect in segment['timed_effects']:
                points.append((origin+effect['start']+effect['duration']/2, effect['name']))
            for effect in segment.get('fx', []):
                points.append((origin+(effect['start']+effect['end'])/2, effect['name']))
        for reaction in evidence['reactions']:
            points.append((evidence['timeline'][reaction['segment']]['start']+reaction['start']+
                           reaction['duration']/2, 'reaction '+reaction['speaker']))
        points.append((duration-1, 'outro'))
        points.sort()
        (directory/'review_samples.json').write_text(json.dumps(points, indent=2))
        frames = []
        for timestamp, label in points:
            raw = subprocess.check_output(['ffmpeg','-v','error','-threads','2','-ss',str(max(0,min(timestamp,duration-.1))),
                '-i',str(master),'-frames:v','1','-vf','scale=320:-2','-f','image2pipe','-vcodec','png','-'])
            frames.append((Image.open(io.BytesIO(raw)).convert('RGB'), f'{timestamp:.2f}s {label}'))
        for page in range(math.ceil(len(frames)/24)):
            sheet(frames[page*24:(page+1)*24], directory/f'contact_{page+1:02}.jpg')
        thumbs = [(Image.open(p).convert('RGB'), p.name) for p in sorted((directory/'share').glob('thumbnail*.jpg'))]
        if thumbs:
            sheet(thumbs, directory/'thumbnails.jpg')
        cards = [json.loads(p.read_text()) for p in (directory/'cards').glob('*.json')]
        candidates = job['share_kit']['metadata'].get('thumbnail_candidates', [])
        speakers = sorted({r['speaker'] for r in evidence['reactions']})
        facts = dict(duration=duration, cap=cap, speakers=speakers, sam=evidence['sam'],
            ai_cards=sum(not c['fallback'] for c in cards),
            ai_thumbnails=sum(c['provider']=='gemini' for c in candidates),
            warnings=job.get('warnings', []), event_samples=len(points),
            master_bytes=master.stat().st_size, discord_bytes=discord.stat().st_size,
            decode_verified=True, audio_codec=audio_streams[0]['codec_name'],
            source_attribution=(ROOT/'ATTRIBUTION.txt').read_text() if directory.name.startswith('deadlock') else None)
        (directory/'verification.json').write_text(json.dumps(facts, indent=2))
        summary.append(f"| {directory.name} | {duration:.3f} / {cap} | {master.stat().st_size/1e6:.1f} / {discord.stat().st_size/1e6:.1f} | {', '.join(speakers)} | {len(evidence['sam'])} | {facts['ai_cards']}/2 | {facts['ai_thumbnails']}/{len(candidates)} |")
        print('PACKAGED',directory.name,flush=True)
    summary += ['', 'Each folder contains full job warnings, stage timings, share kit, event sample manifest and contact sheets.',
                '', (ROOT/'ATTRIBUTION.txt').read_text()]
    (ROOT/'SUMMARY.md').write_text('\n'.join(summary))


if __name__ == '__main__':
    main()
