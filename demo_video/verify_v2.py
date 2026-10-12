"""Decode each deliverable and verify measured DEMO-02 constraints."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
from PIL import Image
from assemble import probe

OUT=Path('/srv/demo_out/demo02')


def main():
    expected={'montage_landscape.mp4':(60,1920,1080),
              'montage_vertical.mp4':(30,1080,1920),
              'montage_mean_vertical.mp4':(20,1080,1920),
              'extension_demo_v2.mp4':(None,1920,1080),
              'extension_demo_v2_discord.mp4':(None,1280,720),
              'ui_walkthrough.mp4':(None,1920,1080),'comparison.mp4':(None,1920,1080)}
    results={}
    for name,(target,width,height) in expected.items():
        path=OUT/name
        media=probe(path)
        video=next(s for s in media['streams'] if s['codec_type']=='video')
        audio=next(s for s in media['streams'] if s['codec_type']=='audio')
        duration=float(media['format']['duration'])
        assert (video['width'],video['height'])==(width,height),name
        assert video['codec_name']=='h264' and audio['codec_name']=='aac',name
        assert video['r_frame_rate']=='30/1',name
        if target is not None:assert abs(duration-target)<.3,(name,duration,target)
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True)
        results[name]=dict(duration=duration,bytes=path.stat().st_size,width=width,height=height,
                           sha256=hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),decoded=True)
        if name.startswith('montage_'):
            volume=subprocess.run(['ffmpeg','-hide_banner','-i',str(path),'-vn','-af','volumedetect',
                                   '-f','null','-'],capture_output=True,text=True,check=True)
            match=re.search(r'mean_volume: (-?[0-9.]+) dB',volume.stderr)
            assert match and float(match[1])>-55, f'{name}: silent audio'
            results[name]['mean_volume_db']=float(match[1])
    assert results['extension_demo_v2_discord.mp4']['bytes']<20_000_000
    assert Image.open(OUT/'contact_sheet.jpg').size==(1920,810)
    evidence=json.loads((OUT/'evidence.json').read_text())
    assert evidence['source_seconds']>1800
    assert evidence['windows_scored']>=38
    assert evidence['calls']['used']<=80
    assert all(any(k.startswith('reactions_') for k in evidence['timings'][n]) for n in ('landscape','vertical','mean_vertical'))
    (OUT/'verification.json').write_text(json.dumps(results,indent=2))
    (OUT/'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {n}\n" for n,r in results.items()))
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
