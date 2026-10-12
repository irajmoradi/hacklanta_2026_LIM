"""Explicit live smoke: stock HTTP API; key read from stdin, never persisted.

Run on runner after remote_run sync. Exactly one analysis job; 25-call job
budget, one attempt per call, 12 candidate windows plus whole-video analysis.
All exports reuse that job. No other paid providers are enabled.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'demo_video/audit/out'
APP = ROOT / 'full_app'

def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, default=str))

def api(path, data=None):
    req = urllib.request.Request('http://127.0.0.1:8000'+path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type':'application/json'} if data is not None else {})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)

def wait(job, label):
    for _ in range(2400):
        data = api('/api/jobs/'+job)
        save(label+'.json', data)
        if data['status'] in ('planned','done','error','cancelled'):
            print(label, data['status'], data.get('error'), flush=True)
            return data
        time.sleep(2)
    raise TimeoutError(label)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    key = sys.stdin.readline().strip()
    if not key: raise RuntimeError('Supply key on stdin')
    os.environ.update(GOOGLE_API_KEY=key, GOOGLE_GENAI_USE_VERTEXAI='true',
        MAX_GEMINI_CALLS_PER_JOB='25', GEMINI_ATTEMPTS='1', GEMINI_TOP_N='12',
        GAME_DETECTION_VLM='0', JOB_WORKSPACE=str(OUT/'workspace'),
        REACTION_PACK=str(APP/'reaction_packs/team'), JOB_WORKERS='1')
    del key
    for var in ('GEMINI_API_KEY','ELEVENLABS_API_KEY','SOCIAL_GEMINI_IMAGES'):
        os.environ.pop(var, None)
    pack=APP/'reaction_packs/team'
    shutil.copytree('/srv/packs/team', pack, dirs_exist_ok=True)
    sam=importlib.util.find_spec('sam2') is not None
    os.environ.update(SAM_BACKEND='local' if sam else 'fallback',
        SAM2_CHECKPOINT='/srv/models/sam2.1_hiera_small.pt')
    save('environment.json', {'sam2_importable':sam, 'checkpoint_exists':Path(os.environ['SAM2_CHECKPOINT']).exists(),
        'model':os.environ.get('GEMINI_MODEL','gemini-3.1-flash-lite-preview'),
        'max_calls':25,'top_n':12,'source':'/srv/demo_in/valorant_phoenix_44k.mp4'})
    # Pick the four-minute window with the most high-energy audio seconds.
    import numpy as np
    source='/srv/demo_in/valorant_phoenix_44k.mp4'
    pcm=subprocess.check_output(['ffmpeg','-v','error','-i',source,'-vn','-ac','1','-ar','1000','-f','f32le','pipe:1'])
    audio=np.frombuffer(pcm,dtype=np.float32)
    energy=np.sqrt(np.mean(audio[:len(audio)//1000*1000].reshape(-1,1000)**2,axis=1))
    score=np.convolve((energy>np.quantile(energy,.7)).astype(float),np.ones(240),mode='valid')
    start=int(np.argmax(score))
    save('trim.json', {'start':start,'end':start+240,'method':'maximum count of top-30-percent RMS seconds in a 240s window',
        'energetic_seconds':score[start]})
    trim=OUT/'input_4min.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',source,'-t','240',
        '-c:v','libx264','-preset','ultrafast','-crf','24','-threads','2','-c:a','aac',str(trim)],check=True)
    log=open(OUT/'server.log','w')
    server=subprocess.Popen([sys.executable,'app.py'],cwd=APP,env=os.environ,stdout=log,stderr=log)
    save('server.json', {'pid':server.pid,'port':8000})
    for _ in range(60):
        try:
            api('/api/health'); break
        except Exception: time.sleep(1)
    else: raise RuntimeError('Server failed to start')
    # curl multipart uses the real upload/probe/resource path, not an injected job.
    uploaded=json.loads(subprocess.check_output(['curl','-sf','-F','video=@'+str(trim),
        'http://127.0.0.1:8000/api/jobs']))
    save('upload.json', uploaded)
    job=uploaded['id']
    options=dict(full_experience=True,window_scoring=True,privacy=False,
        game='auto',preset='landscape',mode='nice',max_duration=45)
    save('requested_options.json',options)
    api('/api/jobs/'+job+'/analyze', options)
    planned=wait(job,'analyzed')
    if planned['status']=='error': return 1
    for label,preset,mode,length in [('landscape','landscape','nice',45),('vertical','vertical','nice',30),('mean_vertical','vertical','mean',30)]:
        settings={**options,'preset':preset,'mode':mode,'max_duration':length}
        api('/api/jobs/'+job+'/plan',settings)
        planned=wait(job,label+'_planned')
        if planned['status']=='error': continue
        api('/api/jobs/'+job+'/render',settings)
        result=wait(job,label)
        if result['status']=='done':
            urllib.request.urlretrieve('http://127.0.0.1:8000'+result['download_url'],OUT/(label+'.mp4'))
            shutil.copytree(OUT/'workspace'/job/'share',OUT/(label+'_share'),dirs_exist_ok=True)
    db=OUT/'workspace'/job/'gemini-budget.sqlite3'
    with sqlite3.connect(db) as conn: calls=conn.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
    save('calls.json', {'gemini_attempts':calls,'limit':25,'other_paid_calls':0})
    return 0

if __name__=='__main__':
    raise SystemExit(main())
