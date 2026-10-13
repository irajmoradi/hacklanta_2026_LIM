"""Explicit live launcher. Read runtime key, transmit via SSH stdin, never save it."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    repo = Path(__file__).resolve().parents[2]
    values = {}
    for line in Path('C:/Users/mourn/Downloads/hacklanta/.env').read_text(encoding='utf-8-sig').splitlines():
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'GOOGLE_API_KEY':
            values['GOOGLE_API_KEY'] = value.strip().strip('"').strip("'")
    assert values.get('GOOGLE_API_KEY'), 'Runtime key missing'
    values.update(GOOGLE_GENAI_USE_VERTEXAI='true', GEMINI_MODEL='gemini-3.5-flash-lite',
                  MAX_GEMINI_CALLS_PER_JOB='60', GEMINI_ATTEMPTS='2', GEMINI_TOP_N='3',
                  IRAJ_DL_LIVE_SMOKE='1', GAME_DETECTION_VLM='0', OMP_THREAD_LIMIT='1')
    host = (repo/'tools/runner_ip').read_text().strip()
    script = 'live_smoke.py'
    command = "cd /srv/lim/lim-irajdl/full_app && ../.venv/bin/python -c 'import json,os,subprocess,sys; env=dict(os.environ,**json.load(sys.stdin)); env[\"PYTHONPATH\"]=os.getcwd(); sys.exit(subprocess.call([sys.executable,\"../demo_video/iraj_deadlock/" + script + "\"],env=env))'"
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/village_vultr'),
                             '-o', 'ServerAliveInterval=20', 'root@'+host, command],
                            input=json.dumps(values).encode(), stderr=subprocess.STDOUT)
    print('Live runner exit=' + str(result.returncode), flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()

