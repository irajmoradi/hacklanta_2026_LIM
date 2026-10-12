"""Read-only saved-demo audit; never reads credentials or calls models."""
import json
import shutil
from pathlib import Path


if __name__ == '__main__':
    for path in Path('/srv/demo_out/demo02').glob('planned_*.json'):
        job = json.loads(path.read_text())
        plan = job.get('edit_plan', job.get('plan', {}))
        print(path.name, 'keys', list(job), 'source', job.get('source'), 'options', job.get('options'))
        print('plan', json.dumps(plan)[:4000])
    print('espeak', shutil.which('espeak'), shutil.which('espeak-ng'))
    for folder in ('/srv/demo_out', '/srv/lim'):
        print('packs', list(Path(folder).glob('**/pack.json'))[:30])
