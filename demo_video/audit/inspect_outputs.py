"""Read-only evidence extraction; no model calls or product-code changes."""
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo_video/audit/out'

def save(path,data): path.write_text(json.dumps(data,indent=2,default=str))

def contact(video, events, target):
    target.mkdir(parents=True,exist_ok=True)
    cap=cv2.VideoCapture(str(video))
    total=cap.get(cv2.CAP_PROP_FRAME_COUNT)/max(1,cap.get(cv2.CAP_PROP_FPS))
    rows=[]
    for i,(when,label) in enumerate(sorted(events)):
        when=max(0,min(total-.05,float(when)))
        cap.set(cv2.CAP_PROP_POS_MSEC,when*1000)
        ok,frame=cap.read()
        if not ok: continue
        im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        im.thumbnail((384,300))
        cell=Image.new('RGB',(400,340),'#141414')
        cell.paste(im,((400-im.width)//2,0))
        draw=ImageDraw.Draw(cell)
        draw.text((5,302),f'{when:.3f}s {label[:52]}',fill='white')
        name=f'{i:04d}_{when:.3f}.jpg'
        cell.save(target/name,quality=88)
        rows.append(dict(time=when,label=label,file=name))
    cap.release()
    for page in range((len(rows)+19)//20):
        sheet=Image.new('RGB',(1600,1700),'#141414')
        for j,row in enumerate(rows[page*20:(page+1)*20]):
            sheet.paste(Image.open(target/row['file']),((j%4)*400,(j//4)*340))
        sheet.save(target/f'contact_{page:02}.jpg',quality=88)
    save(target/'events.json',rows)
    return len(rows)

def inspect(label):
    job=json.loads((OUT/(label+'.json')).read_text())
    video=OUT/(label+'.mp4')
    if not video.exists():
        # A failed post-render share stage can leave valid media: preserve and label it.
        candidate=OUT/'workspace'/job['id']/'output.mp4'
        if candidate.exists():
            import shutil
            shutil.copyfile(candidate,video)
        else: return dict(status=job['status'],error=job.get('error'),no_video=True)
    plan=job.get('render_plan') or job.get('edit_plan') or {}
    timeline=job.get('render_evidence',{}).get('timeline',[])
    events=[(0,'opening'),(.5,'intro'),(1.5,'first play')]
    segments=[]
    for i,seg in enumerate(plan.get('segments',[])):
        clock=timeline[i] if i<len(timeline) else {'start':0,'duration':0}
        row={'index':i,**clock,'source_start':seg['source_start'],'source_end':seg['source_end'],
            'speed':seg.get('speed',1),'video_effects':seg.get('video_effects',[]),
            'timed_effects':seg.get('timed_effects',[]),'fx':seg.get('fx',[]),
            'sfx':seg.get('sound_effects',[]),'words':len(seg.get('words',[])),
            'texts':seg.get('texts',[]),'sam':seg.get('sam'),'reactions':seg.get('reactions',[])}
        segments.append(row)
        base=clock['start']
        events.append((base+.1,f'segment {i} start/transition'))
        for e in seg.get('timed_effects',[]):
            for offset,phase in [(0,'start'),(.5,'mid'),(.9,'end')]:
                events.append((base+e['start']+e['duration']*offset,f"s{i} {e['name']} {phase}"))
        for e in seg.get('fx',[]): events.append((base+(e['start']+e['end'])/2,f"s{i} fx {e['name']}"))
        for e in seg.get('reactions',[]): events.append((base+e['start']+e['duration']/2,f"s{i} reaction {e['label']}"))
        for e in seg.get('words',[]): events.append((base+(e['start']+e['end'])/2,f"s{i} word {e['text']}"))
        for e in seg.get('texts',[]): events.append((base+e['start']+e['duration']/2,f"s{i} text {e['content']}"))
    for e in job.get('render_evidence',{}).get('sam',[]):
        events.append((timeline[e['segment']]['start']+e['time'],'SAM spotlight'))
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
    duration=float(probe['format']['duration'])
    events.append((duration-.5,'outro'))
    n=contact(video,events,OUT/(label+'_frames'))
    pcm=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1']),dtype=np.float32)
    audio=dict(rms=float(np.sqrt(np.mean(pcm**2))),peak=float(np.max(np.abs(pcm))),
        samples=int(pcm.size),near_full_scale_fraction=float(np.mean(np.abs(pcm)>.99)),
        caveat='AAC stream and nonzero PCM do not identify SFX/music/narration separately. Use render graphs and placement evidence.')
    save(OUT/(label+'_probe.json'),probe)
    save(OUT/(label+'_segments.json'),segments)
    save(OUT/(label+'_audio.json'),audio)
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True)
    return dict(status=job['status'],error=job.get('error'),duration=duration,
        dimensions=[probe['streams'][0]['width'],probe['streams'][0]['height']],
        frames=n,segments=len(segments),sfx=sum(len(s['sfx']) for s in segments),
        timed_effects=sum(len(s['timed_effects']) for s in segments),words=sum(s['words'] for s in segments),
        reactions=job.get('render_evidence',{}).get('reactions',[]),
        sam=job.get('render_evidence',{}).get('sam',[]),
        music=plan.get('music'),transition=plan.get('transition'),warnings=job.get('warnings'),
        narration=job.get('narration_track'),sha256=hashlib.sha256(video.read_bytes()).hexdigest())

if __name__=='__main__':
    summary={}
    for name in ('landscape','vertical','mean_vertical'):
        if (OUT/(name+'.json')).exists(): summary[name]=inspect(name)
    if (OUT/'input_4min.mp4').exists():
        contact(OUT/'input_4min.mp4',[(t,f'source +{t}s') for t in range(0,240,10)],OUT/'source_frames')
    save(OUT/'summary.json',summary)
    print(json.dumps(summary,indent=2))
