"""Read-only inventory of saved owner renders; no provider calls."""
import json
from pathlib import Path

root = Path('/srv/demo_out/iraj_deadlock')
for name in ('hype', 'meme', 'cinematic'):
    job = json.loads((root / f'{name}-status.json').read_text())
    print(name, 'keys', sorted(job))
    print('options', job['options'])
    print('plan', json.dumps(job['edit_plan'])[:3500])
    print('job assets', list((root / 'jobs' / job['id']).iterdir()))
print('cards', list((root / 'cards').iterdir()))
