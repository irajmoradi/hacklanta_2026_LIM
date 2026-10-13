"""Offline decode/size checks and contacts at every executed event placement."""
import io
import json
from pathlib import Path
import subprocess
import sys
import shutil

from PIL import Image, ImageDraw, ImageOps
from services.probe import probe_video


def event_samples(data, duration):
    plan = data['render_plan']
    timeline = data['render_evidence']['timeline']
    events = []

    def add(timestamp, label):
        events.append(dict(time=round(max(0, min(duration-.05, timestamp)), 4), label=label))

    if plan.get('intro'):
        add(plan['intro']['duration']/2, 'intro card')
    if plan.get('outro'):
        add(duration-plan['outro']['duration']/2, 'outro card')
    for i, (segment, timing) in enumerate(zip(plan['segments'], timeline)):
        base, length = timing['start'], timing['duration']
        add(base+length/2, f'segment {i}: source {segment["source_start"]:.1f}s')
        if i and plan.get('transition', 'cut') != 'cut':
            add(base+plan['transition_duration']/2, f'transition {i}')
        for effect in segment.get('video_effects', []):
            add(base+length/2, f'segment {i} effect {effect}')
        for key in ('timed_effects', 'reactions', 'texts', 'fx', 'sound_effects'):
            for entry in segment.get(key, []):
                start = entry.get('start', entry.get('offset_in_segment', 0))
                end = min(length, entry.get('end', start+(entry.get('duration') or .1)))
                add(base+(start+end)/2, f'{i} {key}: '+str(entry.get('name') or entry.get('label') or entry.get('sfx_key') or entry.get('content')))
    for entry in data['render_evidence'].get('sam', []):
        i = entry['segment']
        timing = timeline[i]
        add(timing['start']+entry['time'], f'SAM segment {i}')
    return sorted(events, key=lambda event: event['time'])


def contacts(video, events, folder):
    folder.mkdir(exist_ok=True)
    meta = probe_video(video)
    portrait = meta['height'] > meta['width']
    columns, rows, cell_height = (2, 2, 900) if portrait else (3, 4, 340)
    per_page = columns*rows
    pages = []
    for page_start in range(0, len(events), per_page):
        sheet = Image.new('RGB', (columns*480, rows*cell_height), '#151515')
        for cell, event in enumerate(events[page_start:page_start+per_page]):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(event['time']),
                '-i', str(video), '-frames:v', '1', '-vf', 'scale=480:-2',
                '-f', 'image2pipe', '-vcodec', 'png', '-threads', '1', '-'],
                capture_output=True, check=True, timeout=60).stdout
            frame = Image.open(io.BytesIO(raw)).convert('RGB')
            frame = ImageOps.contain(frame, (480, cell_height-50))
            x, y = cell%columns*480, cell//columns*cell_height
            sheet.paste(frame, (x+(480-frame.width)//2, y))
            ImageDraw.Draw(sheet).text((x+5, y+cell_height-46),
                f'{event["time"]:.3f}s | {event["label"][:65]}', fill='white')
        path = folder/f'contact-{page_start//per_page+1:02d}.jpg'
        sheet.save(path, quality=94)
        pages.append(str(path))
    return pages


def main():
    root = Path(sys.argv[1] if len(sys.argv)>1 else '/srv/demo_out/iraj_deadlock')
    results = {}
    for name, target, vertical in [('hype', 60, False), ('meme', 30, True), ('cinematic', 45, False)]:
        status = root/f'{name}-status.json'
        if not status.exists():
            continue
        data = json.loads(status.read_text())
        folder = root/name
        if name != 'hype':
            # Stock limits thumbnails to four attempts per job. Keep the raw
            # share kit intact and offer earlier AI art with honest provenance.
            earlier = root/'hype'/'share'/'metadata.json'
            if earlier.exists():
                alternatives = folder/'ai-thumbnail-alternates'
                alternatives.mkdir(exist_ok=True)
                reused = []
                for candidate in json.loads(earlier.read_text()).get('thumbnail_candidates', []):
                    if candidate['provider'] != 'gemini':
                        continue
                    for variant in candidate['variants'].values():
                        filename = Path(variant['file']).name
                        shutil.copy2(earlier.parent/filename, alternatives/filename)
                        reused.append(dict(file=filename, provider='gemini', reused_from='hype/share',
                                           reason='Stock four-attempt thumbnail budget per job'))
                (alternatives/'provenance.json').write_text(json.dumps(reused, indent=2))
        master, discord = folder/'master.mp4', folder/'discord.mp4'
        meta = probe_video(master)
        assert target-3 <= meta['duration'] <= target+.1, (name, meta)
        assert (meta['height'] > meta['width']) == vertical
        assert data['options']['full_experience'] and data['options']['privacy'] is False
        assert data.get('share_kit', {}).get('downloads')
        for video in [master]:
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video),
                            '-f', 'null', '-'], check=True, timeout=300)
        try:
            complete = discord.is_file() and abs(probe_video(discord)['duration']-meta['duration']) < .1
        except (ValueError, OSError, subprocess.SubprocessError):
            complete = False
        if not complete:
            # Capped bitrate with headroom avoids muxer-dependent two-pass frame
            # counts. Publish only a successfully finished encode.
            rate = int((19_000_000*8/meta['duration']-128_000)*.93)
            temporary = folder/'discord-encoding.mp4'
            args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(master),
                    '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'fps=30', '-fps_mode', 'cfr',
                    '-c:v', 'libx264', '-preset', 'fast', '-b:v', str(rate), '-threads', '2',
                    '-maxrate', str(rate), '-bufsize', str(rate*2), '-c:a', 'aac', '-b:a', '96k',
                    '-t', str(meta['duration']), '-movflags', '+faststart', str(temporary)]
            subprocess.run(args, check=True, timeout=600)
            assert temporary.stat().st_size < 20_000_000
            temporary.replace(discord)
        assert discord.stat().st_size < 20_000_000
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(discord), '-f', 'null', '-'], check=True)
        events = event_samples(data, meta['duration'])
        (folder/'events.json').write_text(json.dumps(events, indent=2))
        sheets = contacts(master, events, folder/'contacts')
        results[name] = dict(meta=meta, master_bytes=master.stat().st_size,
            discord_bytes=discord.stat().st_size, event_count=len(events), contact_sheets=sheets,
            timings=data['timings'], warnings=data['warnings'])
    (root/'verification.json').write_text(json.dumps(results, indent=2))
    summary_file = root/'results.json'
    count_file = root/'analysis-calls.json'
    if summary_file.exists() and count_file.exists():
        summary = json.loads(summary_file.read_text())
        summary['analysis_calls'] = json.loads(count_file.read_text())['calls']
        summary['analysis_timings'] = json.loads((root/'analysis-status.json').read_text())['timings']
        summary_file.write_text(json.dumps(summary, indent=2))
    print(json.dumps(results), flush=True)
    if '--partial' not in sys.argv:
        assert len(results) == 3, 'Not all requested exports are present yet'


if __name__ == '__main__':
    main()
