"""Read-only, credential-free progress and durable call-count audit."""
import json
from pathlib import Path
import sqlite3


def main():
    root = Path('/srv/demo_out/iraj_deadlock')
    marker = root/'job-id.txt'
    data = json.loads((root/'latest-status.json').read_text())
    calls = 0
    if marker.exists():
        ledger = root/'jobs'/marker.read_text().strip()/'gemini-budget.sqlite3'
        if ledger.exists():
            with sqlite3.connect(f'file:{ledger}?mode=ro', uri=True) as db:
                calls = db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
    print(json.dumps(dict(status=data['status'], stage=data.get('pipeline_stage'),
        game=data.get('game'), clips=len(data.get('clips') or []), calls=calls,
        timings=data.get('timings'), warnings=data.get('warnings')), indent=2))


if __name__ == '__main__':
    main()
