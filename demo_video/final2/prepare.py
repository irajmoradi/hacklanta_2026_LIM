"""Runner-only preparation. No credentials or provider calls."""
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[2]
ROOT = Path('/srv/demo_out/final2')
ROOT.mkdir(parents=True, exist_ok=True)
shutil.copytree('/srv/packs/team', REPO/'full_app/reaction_packs/team', dirs_exist_ok=True)
shutil.copyfile('/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.ATTRIBUTION.txt', ROOT/'ATTRIBUTION.txt')
analysis = json.loads(Path('/srv/demo_out/demo02/analysis.json').read_text())
clips = analysis.get('clips', [])
starts = [float(c['start_seconds']) for c in clips]
anchor = max(range(0, max(1, int(max(starts, default=600))-599), 10),
             key=lambda t: sum(t <= s < t+600 for s in starts))
trim = ROOT/'valorant_10min.mp4'
if not trim.exists():
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(anchor), '-i',
        '/srv/demo_in/valorant_phoenix_44k.mp4', '-t', '600', '-vf', 'scale=1280:720,fps=30',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-threads', '2',
        '-c:a', 'aac', '-movflags', '+faststart', str(trim)], check=True)
(ROOT/'source_selection.json').write_text(json.dumps(dict(valorant_start=anchor,
    duration=600, saved_events=sum(anchor <= s < anchor+600 for s in starts),
    reason='Densest ten-minute window by saved DEMO-02 clip starts; fresh stock API analysis.'), indent=2))
print((ROOT/'source_selection.json').read_text(), flush=True)
