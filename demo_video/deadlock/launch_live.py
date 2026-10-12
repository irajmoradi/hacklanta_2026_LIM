"""Explicit live launcher. Read runtime key, transmit via SSH stdin, never save it."""
import json
from pathlib import Path
import subprocess


def main():
    repo = Path(__file__).resolve().parents[2]
    values = {}
    for line in Path('C:/Users/mourn/Downloads/hacklanta/.env').read_text(encoding='utf-8-sig').splitlines():
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'GOOGLE_API_KEY':
            values['GOOGLE_API_KEY'] = value.strip().strip('"').strip("'")
    assert values.get('GOOGLE_API_KEY'), 'Runtime key missing'
    values.update(GOOGLE_GENAI_USE_VERTEXAI='true', GEMINI_MODEL='gemini-3.5-flash-lite',
                  MAX_GEMINI_CALLS_PER_JOB='50', GEMINI_ATTEMPTS='1', GEMINI_TOP_N='12',
                  DEADLOCK_LIVE_SMOKE='1', GAME_DETECTION_VLM='0', OMP_THREAD_LIMIT='1')
    host = (repo/'tools/runner_ip').read_text().strip()
    command = "cd /srv/lim/lim-deadlock1/full_app && ../.venv/bin/python -c 'import json,os,subprocess,sys; env=dict(os.environ,**json.load(sys.stdin)); env[\"PYTHONPATH\"]=os.getcwd(); sys.exit(subprocess.call([sys.executable,\"../demo_video/deadlock/live_smoke.py\"],env=env))'"
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/village_vultr'),
                             '-o', 'ServerAliveInterval=20', 'root@'+host, command],
                            input=json.dumps(values).encode())
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
