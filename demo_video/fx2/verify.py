"""Decode outputs, inspect audio peaks, check plan reproducibility, export QA frames."""
import json
import array
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'full_app'))
from services.fx_planning import restack_saved_job

out = Path('/srv/demo_out/fx2')
verification = {}
for name in ('landscape', 'vertical', 'mean_vertical'):
    saved = json.loads((Path('/srv/demo_out/demo02')/f'planned_{name}.json').read_text())
    plan = json.loads((out/f'planned_{name}.json').read_text())
    expected = json.loads(json.dumps(restack_saved_job(saved, seed=2026)))
    assert plan == expected, f'{name}: stale plan'
    output = out/f'montage_{name}.mp4'
    result = subprocess.run(['ffmpeg','-v','info','-i',str(output),'-af','volumedetect',
                             '-f','null','-'],capture_output=True,text=True,check=True)
    audio = [line.strip() for line in result.stderr.splitlines() if 'mean_volume:' in line or 'max_volume:' in line]
    assert audio and not any('-inf' in line for line in audio), 'Silent output'
    peaks = {}
    for media in (output, out/f'montage_{name}_discord.mp4'):
        raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(media),'-vn','-f','f32le','-'])
        samples = array.array('f')
        samples.frombytes(raw)
        peak = max(abs(s) for s in samples)
        assert 0 < peak < 1, f'{media.name}: silent or over full scale ({peak})'
        peaks[media.name] = dict(peak=peak, dbfs=20*math.log10(peak))
    for i, segment in enumerate(plan['planner_plan']['clips'][:3]):
        effects = [e for e in plan['planner_plan']['effects'] if e['clip_id']==segment['id'] and e['name']!='slow_motion']
        time = max(e['start'] for e in effects)+.1
        time = min(time, segment['start']+segment['duration']-.05)
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(time),'-i',str(output),'-frames:v','1',
                        '-vf','scale=640:-2',str(out/f'qa_{name}_{i}.jpg')],check=True)
    metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
    duration = float(metadata['format']['duration'])
    assert abs(duration-plan['planner_plan']['duration']) < .2
    assert (out/f'montage_{name}_discord.mp4').stat().st_size < 20_000_000
    verification[name] = dict(duration=duration, audio=audio, peaks=peaks, decode_exit=0, reproducible_plan=True)
(out/'verification.json').write_text(json.dumps(verification,indent=2))
print(json.dumps(verification,indent=2))
