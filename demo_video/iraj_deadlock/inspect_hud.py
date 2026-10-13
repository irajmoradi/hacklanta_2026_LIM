"""Offline bounded HUD diagnostic, no participant OCR persisted."""
import io
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw
from profiles import get_profile
from profiles.hud import layout_evidence
from profiles.detection import tesseract_ocr
from services.probe import probe_video

SOURCE = '/srv/demo_in/deadlock_iraj_gfn_20261012.mp4'
ROOT = Path('/srv/demo_out/iraj_deadlock/hud')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    duration = probe_video(SOURCE)['duration']
    sheet = Image.new('RGB', (1280, 4*380))
    rows = []
    for i in range(16):
        timestamp = duration*(i+.5)/16
        png = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(timestamp), '-i', SOURCE,
            '-frames:v', '1', '-vf', 'scale=1280:-1', '-f', 'image2pipe', '-vcodec', 'png', '-'],
            capture_output=True, check=True).stdout
        (ROOT/f'{i:02d}.png').write_bytes(png)
        cues = layout_evidence(png, get_profile('deadlock'), tesseract_ocr)
        rows.append(dict(index=i, timestamp=timestamp, cues=cues))
        frame = Image.open(io.BytesIO(png)).resize((320, 180))
        x, y = i%4*320, i//4*380
        sheet.paste(frame, (x, y))
        ImageDraw.Draw(sheet).text((x+5, y+185), f'{i}: {timestamp:.1f}s\n{cues}', fill='white')
    sheet.save(ROOT/'contact.jpg')
    (ROOT/'cues.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows), flush=True)


if __name__ == '__main__':
    main()
