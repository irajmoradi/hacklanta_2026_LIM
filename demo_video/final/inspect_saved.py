import json
from pathlib import Path
for name in ('analysis.json', 'planned_landscape.json', 'planned_mean_vertical.json'):
    job = json.loads((Path('/srv/demo_out/demo02')/name).read_text())
    print(name, list(job), len(job.get('clips', [])), job.get('options'))
    if name.startswith('planned'):
        print('clips:', [(c['id'], c['start_seconds'], c['end_seconds'], c.get('type')) for c in job['clips']])
pack = json.loads(Path('/srv/packs/team/pack.json').read_text())
print('speakers', sorted({c['speaker'] for c in pack['clips']}))
print('example', pack['clips'][-1])
