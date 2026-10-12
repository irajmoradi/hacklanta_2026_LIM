"""Explicit DEMO-02 live smoke launcher: credentials go over SSH stdin, never to disk."""
import json
import os
from pathlib import Path
import subprocess


def main():
    repo = Path(__file__).resolve().parents[1]
    dotenv = Path('C:/Users/mourn/Downloads/hacklanta/.env')
    values = {}
    for line in dotenv.read_text(encoding='utf-8-sig').splitlines():
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'GOOGLE_API_KEY':
            values['GOOGLE_API_KEY'] = value.strip().strip('"').strip("'")
    assert values.get('GOOGLE_API_KEY'), 'Runtime GOOGLE_API_KEY unavailable'
    values.update(GOOGLE_GENAI_USE_VERTEXAI='true', GEMINI_MODEL='gemini-3.5-flash-lite',
                  MAX_GEMINI_CALLS_PER_JOB='80', GEMINI_ATTEMPTS='1', GEMINI_TOP_N='40',
                  LIM_DEMO02_LIVE='1', GAME_DETECTION_VLM='0')
    host = (repo / 'tools/runner_ip').read_text().strip()
    key = Path.home() / '.ssh/village_vultr'
    command = "cd /srv/lim/lim-demo02/full_app && ../.venv/bin/python -c 'import json,os,subprocess,sys; env=dict(os.environ,**json.load(sys.stdin)); sys.exit(subprocess.call([sys.executable,\"../demo_video/live_v2.py\"],env=env))'"
    result = subprocess.run(['ssh', '-i', str(key), '-o', 'StrictHostKeyChecking=accept-new',
                             'root@' + host, command], input=json.dumps(values).encode())
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
