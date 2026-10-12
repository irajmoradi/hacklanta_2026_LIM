"""One model-list request, then resume SAME bounded ledger after default failure."""
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

from live_run import ROOT, OUT, APP, api, save, wait

def main():
    os.environ['GOOGLE_API_KEY']=sys.stdin.readline().strip()
    os.environ['GOOGLE_GENAI_USE_VERTEXAI']='true'
    # The one prior models.list request returned 401: Vertex publisher listing
    # requires OAuth, unlike express generation. Do not repeat metadata requests.
    save('available_models.json',{'metadata_calls':1,'status':401,
        'reason':'Publisher-model listing does not support express API-key auth'})
    chosen='gemini-2.5-flash'
    save('analyzed_default_model.json',json.loads((OUT/'analyzed.json').read_text()))
    job=json.loads((OUT/'upload.json').read_text())['id']
    db=OUT/'workspace'/job/'gemini-budget.sqlite3'
    with sqlite3.connect(db) as conn: before=conn.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
    print('Reserved attempts before retry:',before,flush=True)
    pid=json.loads((OUT/'server.json').read_text())['pid']
    os.kill(pid,signal.SIGTERM)
    for _ in range(40):
        try: api('/api/health'); time.sleep(.5)
        except Exception: break
    os.environ.update(GEMINI_MODEL=chosen,MAX_GEMINI_CALLS_PER_JOB='24',GEMINI_ATTEMPTS='1',
        GEMINI_TOP_N='6',GAME_DETECTION_VLM='0',JOB_WORKSPACE=str(OUT/'workspace'),
        REACTION_PACK=str(APP/'reaction_packs/team'),JOB_WORKERS='1',SAM_BACKEND='fallback')
    save('model_override.json',{'model':chosen,'prior_reserved_attempts':before,'metadata_calls':1,
        'shared_generation_limit':24,'total_limit':25,'reason':'Stock model failed; no product changes'})
    log=open(OUT/'server_retry.log','w')
    server=subprocess.Popen([sys.executable,'app.py'],cwd=APP,env=os.environ,stdout=log,stderr=log)
    save('server.json',{'pid':server.pid,'port':8000})
    for _ in range(60):
        try: api('/api/health'); break
        except Exception: time.sleep(1)
    options=json.loads((OUT/'requested_options.json').read_text())
    api('/api/jobs/'+job+'/analyze',options)
    planned=wait(job,'analyzed')
    if planned['status']=='error': return 1
    for label,preset,mode,length in [('landscape','landscape','nice',45),('vertical','vertical','nice',30),('mean_vertical','vertical','mean',30)]:
        settings={**options,'preset':preset,'mode':mode,'max_duration':length}
        api('/api/jobs/'+job+'/plan',settings)
        planned=wait(job,label+'_planned')
        if planned['status']=='error': continue
        api('/api/jobs/'+job+'/render',settings)
        result=wait(job,label)
        # Retain completed media even if a later share-kit error prevents download.
        media=OUT/'workspace'/job/'output.mp4'
        if media.exists(): shutil.copyfile(media,OUT/(label+'.mp4'))
        share=OUT/'workspace'/job/'share'
        if share.exists(): shutil.copytree(share,OUT/(label+'_share'),dirs_exist_ok=True)
    with sqlite3.connect(db) as conn: calls=conn.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
    save('calls.json',{'gemini_attempts':calls,'metadata_calls':1,'total':calls+1,'limit':25,'other_paid_calls':0})
    return 0

if __name__=='__main__': raise SystemExit(main())
