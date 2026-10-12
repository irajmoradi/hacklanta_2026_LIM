"""Local launcher: transfer a runtime-only credential over encrypted SSH stdin.

No key in argv, artifacts, logs, or files. The remote child receives environment
only. This starts an explicitly marked LIVE smoke test with a three-call cap.
"""
import json
from pathlib import Path
import subprocess


def main():
    envfile = Path('C:/Users/mourn/Downloads/hacklanta/.env')
    values = {}
    for line in envfile.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            name, value = line.split('=', 1)
            values[name.strip()] = value.strip().strip('\"\'')
    key = values['GOOGLE_API_KEY']
    remote = '''import json,os,subprocess,sys
payload=json.load(sys.stdin)
env=dict(os.environ,GOOGLE_API_KEY=payload['key'],GOOGLE_GENAI_USE_VERTEXAI='true')
os.makedirs('/srv/demo_out/demo01',exist_ok=True)
with open('/srv/demo_out/demo01/backend.log','ab') as log:
 p=subprocess.Popen(['/srv/lim/lim-demo01/.venv/bin/python','-u','demo_video/live_smoke_server.py'],cwd='/srv/lim/lim-demo01',env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
print('Live smoke backend PID',p.pid)
'''
    # Python code contains no credential. The secret is exclusively in stdin.
    import shlex
    subprocess.run(['ssh', '-i', str(Path.home() / '.ssh/village_vultr'),
                    '-o', 'BatchMode=yes', 'root@104.207.133.47',
                    'python3 -c ' + shlex.quote(remote)],
                   input=json.dumps({'key': key}), text=True, check=True)


if __name__ == '__main__':
    main()
