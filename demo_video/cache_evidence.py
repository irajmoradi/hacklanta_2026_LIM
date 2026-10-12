"""Associate saved real signal evidence with its uploaded source after a failure."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

OUT = Path('/srv/demo_out/demo01')
job_id = (OUT / 'job_id.txt').read_text().strip()
with urlopen('http://127.0.0.1:8011/api/jobs/' + job_id) as response:
    job = json.load(response)
with (OUT / 'jobs' / job_id / 'source.mp4').open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
(OUT / 'local_candidates_source.json').write_text(json.dumps({'sha256': digest}))
(OUT / 'cold_analysis_timings.json').write_text(json.dumps(job['timings'], indent=2))
print('Saved real source fingerprint and cold analysis timings; no network provider used.')
