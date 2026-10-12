"""Non-generating contract and provenance probes; run through remote_run."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo_video/audit/out'
sys.path.insert(0,str(ROOT/'full_app'))
from server.validation import options_valid
from server.legacy import EDIT_STYLES

def write(name,data): (OUT/name).write_text(json.dumps(data,indent=2,default=str))
results={}
for name,data in {'chaos':{'chaos':.6,'seed':7},'clean':{'clean':True},
    'reaction_size':{'reaction_size':'large'},'image':{'gemini_image':True},
    'full':{'full_experience':True},'ui_full_scoring_override':{'full_experience':True,'window_scoring':False},
    'profile':{'profile':'competitive'},'intensity':{'fx_intensity':.8}}.items():
    try: results[name]={'accepted':True,'options':options_valid(data,EDIT_STYLES)}
    except ValueError as e: results[name]={'accepted':False,'reason':str(e)}
for route in ('/api/info','/api/search?q=kill','/api/stats/players'):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000'+route) as r:
            results[route]={'status':r.status,'data':json.load(r)}
    except urllib.error.HTTPError as e: results[route]={'status':e.code}
write('admission_probes.json',results)
pack=Path('/srv/packs/team')
clips=json.loads((pack/'pack.json').read_text())['clips']
write('pack_inventory.json',{'total':len(clips),'speakers':sorted({c['speaker'] for c in clips}),
    'explicit':sum(bool(c.get('explicit')) for c in clips),
    'clips':[{'id':c['id'],'speaker':c['speaker'],'text':c['text'],'duration':c['duration'],
              'explicit':c.get('explicit'),'style':c.get('style'),
              'alpha_exists':bool(c.get('alpha_file') and (pack/c['alpha_file']).exists()),
              'mask_exists':bool(c.get('mask_file') and (pack/c['mask_file']).exists())} for c in clips]})
historical=[]
for directory in ('/srv/demo_out/demo01','/srv/demo_out/demo02','/srv/demo_out/wire1','/srv/demo_out/final','/srv/demo_out/fx3','/srv/demo_out/deadlock'):
    folder=Path(directory)
    entry={'directory':directory,'exists':folder.exists(),'files':[]}
    if folder.exists():
        for p in sorted(folder.glob('*')):
            if p.is_file():
                item={'file':p.name,'bytes':p.stat().st_size}
                if p.suffix=='.mp4':
                    r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(p)],capture_output=True,text=True)
                    item.update(probe_exit=r.returncode,probe=json.loads(r.stdout) if r.returncode==0 else {})
                entry['files'].append(item)
    historical.append(entry)
write('provenance.json',historical)
upload=OUT/'upload.json'
if upload.exists():
    job=json.loads(upload.read_text())['id']
    db=OUT/'workspace'/job/'gemini-budget.sqlite3'
    if db.exists():
        with sqlite3.connect(db) as conn: count=conn.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
        write('calls_observed.json',{'generation_attempts':count,'metadata_calls':1,'total_upper_bound':count+1,'limit':25})
print('Read-only probes recorded; no inference calls.')
