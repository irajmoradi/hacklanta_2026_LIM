"""Offline packaging, decoded-frame contacts and execution/stream checks."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / 'full_app'), str(REPO)]
from demo_video.iraj_deadlock.verify_outputs import contacts, event_samples
from services.probe import probe_video

ROOT = Path('/srv/demo_out/iraj_deadlock2')
BEFORE = Path('/srv/demo_out/iraj_deadlock')


def dump(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def luma(video, timestamp):
    pixels = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(timestamp),
        '-i', str(video), '-frames:v', '1', '-vf', 'crop=iw*0.6:ih*0.6,scale=160:90,format=gray',
        '-f', 'rawvideo', '-threads', '1', '-'])
    return round(sum(pixels)/len(pixels), 2)


def main():
    report = ROOT / 'verification.json'
    results = json.loads(report.read_text()) if report.exists() else {}
    pack = {r['id']: r for r in json.loads(Path('/srv/packs/team/pack.json').read_text())['clips']}
    for name, cap, vertical in [('hype', 60, False), ('meme', 30, True), ('cinematic', 45, False)]:
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        directory = ROOT / name
        job = json.loads((directory / 'job.json').read_text())
        evidence = job['render_evidence']
        master, discord = directory / 'master.mp4', directory / 'discord.mp4'
        meta = probe_video(master)
        assert cap-3 <= meta['duration'] <= cap+.1
        assert (meta['height'] > meta['width']) == vertical
        assert job['options']['narration'] is False
        assert job['options']['reaction_speakers'] == ['Iraj']
        assert not job.get('narration_track') and 'narration_graph' not in evidence
        assert 'narration' not in job['timings']
        assert evidence['reactions'] and {r['speaker'] for r in evidence['reactions']} == {'Iraj'}
        assert all(pack[r['id']]['speaker'] == 'Iraj' for r in evidence['reactions'])
        assert len({r['id'] for r in evidence['reactions']}) > 1
        before_job = json.loads((BEFORE / f'{name}-status.json').read_text())
        assert [(s['source_start'], s['source_end']) for s in job['edit_plan']['segments']] == [
            (s['source_start'], s['source_end']) for s in before_job['edit_plan']['segments']]
        for role in ('intro', 'outro'):
            assert (directory / 'cards' / f'{role}.png').read_bytes() == (
                BEFORE / 'jobs' / job['id'] / 'cards' / f'{role}.png').read_bytes()
        # Original covers, not newly synthesized images.
        for image in (BEFORE / name / 'share').glob('*.jpg'):
            assert image.read_bytes() == (directory / 'share' / image.name).read_bytes()
        if not discord.exists():
            bitrate = min(2200000, int(18_500_000*8/meta['duration'])-128000)
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(master),
                '-map', '0:v:0', '-map', '0:a:0', '-vf', 'scale=720:1280' if vertical else 'scale=1280:720',
                '-c:v', 'libx264', '-preset', 'fast', '-b:v', str(bitrate), '-maxrate', str(bitrate),
                '-bufsize', str(bitrate*2), '-threads', '2', '-c:a', 'aac', '-b:a', '96k',
                '-movflags', '+faststart', str(discord)], check=True, timeout=600)
        assert discord.stat().st_size < 20_000_000
        streams = {}
        for video in (master, discord):
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-threads', '2', '-i', str(video),
                            '-f', 'null', '-'], check=True, timeout=300)
            info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                '-show_format', '-of', 'json', str(video)]))
            assert [s['codec_type'] for s in info['streams']] == ['video', 'audio']
            assert abs(float(info['format']['duration'])-meta['duration']) < .1
            dump(directory / f'{video.stem}-ffprobe.json', info)
            streams[video.stem] = [dict(type=s['codec_type'], codec=s['codec_name']) for s in info['streams']]
        events = event_samples(job, meta['duration'])
        contacts(master, events, directory / 'contacts')
        reactions = [dict(time=evidence['timeline'][r['segment']]['start']+r['start']+r['duration']/2,
                          label=f"Iraj: {r['id']}") for r in evidence['reactions']]
        contacts(master, reactions, directory / 'reaction-contacts')
        dump(directory / 'events.json', events)
        grade = []
        if name == 'cinematic':
            assert not any(e['name'] in ('dark_mood', 'vignette') for s in job['render_plan']['segments']
                           for e in s['timed_effects'])
            for timing in evidence['timeline']:
                timestamp = timing['start'] + timing['duration']/2
                grade.append(dict(time=timestamp, before=luma(BEFORE / name / 'master.mp4', timestamp),
                                  after=luma(master, timestamp)))
            assert sum(r['after'] for r in grade) > sum(r['before'] for r in grade)
        results[name] = dict(duration=meta['duration'], width=meta['width'], height=meta['height'],
            master_bytes=master.stat().st_size, discord_bytes=discord.stat().st_size,
            master_sha256=hashlib.sha256(master.read_bytes()).hexdigest(), streams=streams,
            reaction_count=len(reactions), reaction_ids=[r['id'] for r in evidence['reactions']],
            speakers=['Iraj'], narration=False, new_gemini_calls=0, decoded=True,
            cinematic_luma=grade, warnings=job['warnings'])
        dump(directory / 'verification.json', results[name])
        print(name, json.dumps(results[name]), flush=True)
    dump(ROOT / 'verification.json', results)


if __name__ == '__main__':
    main()
