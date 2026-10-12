"""No inference diagnostic after a real API render failure; never replaces API proof.

Calls the unmodified renderer on the saved plan in a separate output directory.
The real queue suppresses exceptions and deletes its finished output on failure.
"""
import json
import os
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo_video/audit/out'
sys.path.insert(0,str(ROOT/'full_app'))
os.environ.update(REACTION_PACK=str(ROOT/'full_app/reaction_packs/team'),
                  SAM_BACKEND='fallback',MAX_GEMINI_CALLS_PER_JOB='0')
for key in ('GOOGLE_API_KEY','GEMINI_API_KEY','ELEVENLABS_API_KEY'):
    os.environ.pop(key,None)
from pipeline import Pipeline
from services.probe import probe_video

label=sys.argv[1] if len(sys.argv)>1 else 'landscape'
bounded='--bounded' in sys.argv
suffix='_bounded' if bounded else ''
if bounded:
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
    os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
job=json.loads((OUT/(label+'_planned.json')).read_text())
job['source']=str(OUT/'workspace'/job['id']/'source.mp4')
job['dir']=str(OUT/('diagnostic_'+label+suffix))
Path(job['dir']).mkdir(exist_ok=True)
try:
    Pipeline().render(job,None)
    duration=probe_video(job['output'])['duration']
    result={'render_returned':True,'duration':duration,
            'max_duration':job['options']['max_duration'],
            'worker_duration_guard_passes':duration<=job['options']['max_duration']+.1}
except Exception as error:
    result={'render_returned':False,'exception_type':type(error).__name__,
            'traceback':traceback.format_exc()}
(OUT/(label+suffix+'_diagnostic.json')).write_text(json.dumps(job,indent=2))
(OUT/(label+suffix+'_diagnosis.json')).write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2),flush=True)
