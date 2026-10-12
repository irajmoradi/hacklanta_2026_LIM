"""Stop only audit-owned API/Vite processes after collecting browser evidence."""
import json
import os
from pathlib import Path
import signal

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo_video/audit/out'
rows=[]
for file,expected,group in [('server.json',ROOT/'full_app',False),
                            ('vite_pid.json',ROOT/'full_app/production_frontend',True)]:
    pid=json.loads((OUT/file).read_text())['pid']
    proc=Path('/proc')/str(pid)
    if not proc.exists():
        rows.append({'pid':pid,'already_stopped':True}); continue
    assert (proc/'cwd').resolve()==expected.resolve(),f'Process {pid} no longer belongs to this audit'
    command=(proc/'cmdline').read_bytes()
    assert (b'npm' in command if group else b'app.py' in command),f'Unexpected process {pid}'
    if group:
        assert os.getpgid(pid)==pid
        os.killpg(pid,signal.SIGTERM)
    else: os.kill(pid,signal.SIGTERM)
    rows.append({'pid':pid,'sent':'SIGTERM','own_process_group':group})
(OUT/'server_cleanup.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows))
