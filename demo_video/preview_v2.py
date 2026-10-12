"""Preview the same local planner against saved analysis and review decisions."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'full_app'))
from pipeline import Pipeline
OUT=Path('/srv/demo_out/demo02')


def main():
    decisions=json.loads((ROOT/'demo_video/review_decisions_v2.json').read_text())
    for name,mode,preset,target in [('landscape','nice','landscape',60),('vertical','nice','vertical',30),('mean_vertical','mean','vertical',20)]:
        job=json.loads((OUT/'analysis.json').read_text())
        for c in job['clips']:
            c['keep']=not any(c['start_seconds']==e['start'] and c['end_seconds']==e['end'] for e in decisions['exclude'])
            edit=next((e for e in decisions.get('edits',[]) if c['start_seconds']==e['start'] and c['end_seconds']==e['end']),None)
            if edit:c.update(caption=edit['caption'],editorial_review=True,signals={**c.get('signals',{}),'fail_time':edit['fail_time']})
        job['options'].update(mode=mode,preset=preset,max_duration=target)
        Pipeline().plan(job,None)
        (OUT/('planned_'+name+'.json')).write_text(json.dumps(job,indent=2))


if __name__=='__main__':main()
