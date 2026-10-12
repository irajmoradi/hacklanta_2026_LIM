"""Read-only live attempt audit, sampled independently of the UI driver."""
import json
from pathlib import Path
import sqlite3
import time
from urllib.request import urlopen

ROOT=Path('/srv/demo_out/demo02')


def main():
    job=(ROOT/'job-id.txt').read_text().strip()
    ledger=ROOT/'jobs'/job/'gemini-budget.sqlite3'
    rows=[]
    while True:
        try:
            with urlopen('http://127.0.0.1:8012/api/jobs/'+job) as response:
                d=json.load(response)
        except OSError:
            break
        used=0
        if ledger.exists():
            with sqlite3.connect(ledger) as db:
                used=db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
        row=dict(status=d['status'],stage=d.get('pipeline_stage'),used=used,
                 analysis_complete='analyze' in d['completed'])
        if not rows or any(row[k]!=rows[-1][k] for k in row):
            rows.append(dict(**row,utc=time.time()))
            (ROOT/'attempt_audit.json').write_text(json.dumps(rows,indent=2))
            print(json.dumps(row),flush=True)
        if (ROOT/'montage_mean_vertical.mp4').exists():break
        time.sleep(5)
    completed=[r['used'] for r in rows if r['analysis_complete']]
    assert completed and len(set(completed))==1, 'Paid attempts changed after analysis'
    print('No post-analysis paid attempts:',completed[-1],flush=True)


if __name__=='__main__':main()
