"""Decode every deliverable and verify formats, timing, audio and contact sheet."""
import json
from pathlib import Path
import re
import subprocess
from PIL import Image

OUT=Path('/srv/demo_out/demo01')
SIZES={'extension_demo.mp4':(1920,1080), 'montage_landscape.mp4':(1920,1080),
       'montage_vertical.mp4':(1080,1920), 'montage_mean_vertical.mp4':(1080,1920),
       'ui_walkthrough.mp4':(1920,1080)}


def main():
    results={}
    for name,size in SIZES.items():
        path=OUT/name
        meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))
        video=next(s for s in meta['streams'] if s['codec_type']=='video')
        assert (video['width'],video['height'])==size, name
        assert video['codec_name']=='h264',name
        assert video['r_frame_rate']=='30/1',name
        assert any(s['codec_type']=='audio' and s['codec_name']=='aac' for s in meta['streams']),name
        duration=float(meta['format']['duration'])
        assert 120<=duration<=180 if name=='extension_demo.mp4' else 0<duration<=90,name
        decoded=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],capture_output=True,text=True)
        assert decoded.returncode==0 and not decoded.stderr.strip(), (name,decoded.stderr)
        volume=None
        if name!='ui_walkthrough.mp4':
            audio=subprocess.run(['ffmpeg','-hide_banner','-i',str(path),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True)
            match=re.search(r'mean_volume: (-?[\d.]+) dB',audio.stderr)
            assert match and float(match[1])>-60, (name,'missing or silent audio')
            volume=float(match[1])
        results[name]={'duration':duration,'dimensions':size,'decode_exit':decoded.returncode,'mean_volume_db':volume}
    with Image.open(OUT/'contact_sheet.jpg') as sheet:
        assert sheet.size==(1920,810)
    assert len(json.loads((OUT/'live_calls.json').read_text()))<=3
    (OUT/'verification.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
