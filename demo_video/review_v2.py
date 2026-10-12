"""Source and output contact sheets for manual semantic/overlay review."""
import json
from pathlib import Path
import subprocess
from PIL import Image,ImageDraw,ImageFont

OUT=Path('/srv/demo_out/demo02')
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def frame(source,time,path):
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(max(0,time)),'-i',str(source),
                    '-frames:v','1','-vf','scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2',str(path)],check=True)
    return Image.open(path).convert('RGB')


def main():
    folder=OUT/'review';folder.mkdir(exist_ok=True)
    font=ImageFont.truetype(FONT,16)
    for name in ['landscape','vertical','mean_vertical']:
        d=json.loads((OUT/(name+'.json')).read_text());plan=d['planner_plan']
        clips=plan['clips']
        canvas=Image.new('RGB',(1440,len(clips)*306),'#101824');draw=ImageDraw.Draw(canvas)
        for row,c in enumerate(clips):
            times=[c['source_start'],c['source_start']+(c['peak']-c['start'])*c['speed'],max(c['source_start'],c['source_end']-.3)]
            for col,t in enumerate(times):
                canvas.paste(frame('/srv/demo_in/valorant_phoenix_44k.mp4',t,folder/'frame.jpg'),(col*480,row*306))
                draw.text((col*480+6,row*306+276),f"{c['source_id']} / {c['label']} / {t:.2f}s",font=font,fill='white')
        canvas.save(folder/(name+'_source.jpg'))
        moments=[min(plan['duration']-.2,r['start']+.3) for r in plan['reactions']]
        moments=list(dict.fromkeys([2,*moments,plan['duration']-2]))
        canvas=Image.new('RGB',(1440,((len(moments)+2)//3)*306),'#101824');draw=ImageDraw.Draw(canvas)
        for i,t in enumerate(moments):
            canvas.paste(frame(OUT/('montage_'+name+'.mp4'),t,folder/'frame.jpg'),((i%3)*480,(i//3)*306))
            draw.text(((i%3)*480+6,(i//3)*306+276),f"Output {t:.2f}s",font=font,fill='white')
        canvas.save(folder/(name+'_output.jpg'))
    (folder/'frame.jpg').unlink(missing_ok=True)


if __name__=='__main__':main()
