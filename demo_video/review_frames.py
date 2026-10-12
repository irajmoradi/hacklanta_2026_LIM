"""Source-frame QA contact sheets for human verification of actual clip evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

OUT=Path('/srv/demo_out/demo01')
clips=json.loads((OUT/'analysis.json').read_text())['clips']
folder=OUT/'source_review';folder.mkdir(exist_ok=True)
if '--mean' in sys.argv:
    rows=json.loads((Path(__file__).parent/'editorial_selection.json').read_text())['mean']
    clips=[dict(id=f'mean_{i}_{j}',start_seconds=e['start']+(e['end']-e['start'])*fraction,
                end_seconds=e['start']+(e['end']-e['start'])*fraction+.002,source='editorial mean QA')
           for i,e in enumerate(rows) for j,fraction in enumerate((.2,.5,.85))]
    folder=OUT/'mean_review';folder.mkdir(exist_ok=True)
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',20)

def frame(c):
    path=folder/(c['id']+'.jpg')
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str((c['start_seconds']+c['end_seconds'])/2),
        '-i','/srv/demo_in/valorant_phoenix_44k.mp4','-frames:v','1','-vf','scale=640:360',str(path)],check=True)
    return path

with ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(frame,clips))
for offset in range(0,len(clips),6):
    sheet=Image.new('RGB',(1920,800),'#101824');draw=ImageDraw.Draw(sheet)
    for n,c in enumerate(clips[offset:offset+6]):
        x,y=n%3*640,n//3*400
        sheet.paste(Image.open(folder/(c['id']+'.jpg')),(x,y))
        draw.text((x+10,y+365),f"ID {c['id']}  {c['start_seconds']:.1f}-{c['end_seconds']:.1f}s  {c['source']}",font=font,fill='white')
    sheet.save(folder/f'page_{offset//6}.jpg')
print('Wrote',len(clips),'review frames')
