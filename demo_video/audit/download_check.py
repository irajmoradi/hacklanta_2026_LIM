"""Verify the latest real HTTP output and share-kit routes without inference."""
import hashlib
import json
from pathlib import Path
import urllib.request
from live_run import OUT,api,save

job=json.loads((OUT/'upload.json').read_text())['id']
status=api('/api/jobs/'+job)
assert status['status']=='done'
rows=[]
for suffix in ('download','share/metadata.json','share/thumbnail_youtube.jpg','share/captions.srt'):
    with urllib.request.urlopen('http://127.0.0.1:8000/api/jobs/'+job+'/'+suffix) as response:
        body=response.read()
        rows.append(dict(path=suffix,status=response.status,bytes=len(body),sha256=hashlib.sha256(body).hexdigest()))
assert rows[0]['sha256']==hashlib.sha256((OUT/'mean_vertical.mp4').read_bytes()).hexdigest()
save('http_downloads.json',{'variant':'mean_vertical','checks':rows})
print(json.dumps(rows,indent=2))
