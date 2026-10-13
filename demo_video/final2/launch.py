"""Explicit FINAL-2 live smoke launcher; credentials travel over SSH stdin only."""
import json
from pathlib import Path
import subprocess

repo = Path(__file__).resolve().parents[2]
values = {}
for line in Path('C:/Users/mourn/Downloads/hacklanta/.env').read_text(encoding='utf-8-sig').splitlines():
    name, separator, value = line.partition('=')
    if separator and name.strip() == 'GOOGLE_API_KEY':
        values[name.strip()] = value.strip().strip('"').strip("'")
assert values.get('GOOGLE_API_KEY'), 'Runtime credential unavailable'
values.update(GOOGLE_GENAI_USE_VERTEXAI='true', GEMINI_MODEL='gemini-3.5-flash-lite',
    MAX_GEMINI_CALLS_PER_JOB='30', GEMINI_ATTEMPTS='1', GEMINI_TOP_N='12',
    LIM_FINAL2_LIVE='1', GAME_DETECTION_VLM='0', EDITOR_AGENT_CALL_BUDGET='0', SAM_BACKEND='local',
    SAM2_CHECKPOINT='/srv/models/sam2.1_hiera_small.pt', SAM_TIMEOUT='120',
    SAM_CLIP_BUDGET='300', SAM_MAX_SAMPLES='4', OMP_NUM_THREADS='2',
    OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2',
    REACTION_PACK='/srv/lim/lim-final2/full_app/reaction_packs/team')
command = "cd /srv/lim/lim-final2/full_app && ../.venv/bin/python -c 'import json,os,subprocess,sys; env=dict(os.environ,**json.load(sys.stdin)); sys.exit(subprocess.call([sys.executable,\"../demo_video/final2/live.py\"],env=env))'"
result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/village_vultr'),
    'root@'+(repo/'tools/runner_ip').read_text().strip(), command], input=json.dumps(values).encode())
raise SystemExit(result.returncode)
