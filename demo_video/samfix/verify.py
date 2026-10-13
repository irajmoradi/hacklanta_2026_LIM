"""Decode every output and build a contact sheet of every SAM attempt/reaction."""
import array
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'full_app'))


def main():
    out = Path('/srv/demo_out/samfix')
    cells, verification = [], {}
    for name, target in [('landscape', 60), ('mean_vertical', 30)]:
        job = json.loads((out/f'job_{name}.json').read_text())
        assert not job['options']['privacy']
        evidence = job['render_evidence']
        assert len({r['speaker'] for r in evidence['reactions']}) == 4
        assert len(job['samfix_attempts']) == 3
        for attempt in job['samfix_attempts']:
            assert attempt['accepted'] or any('SAM spotlight skipped' in m for m in attempt['warnings'])
        for suffix in ('', '_discord'):
            path = out/f'montage_{name}{suffix}.mp4'
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'], check=True)
            from services.probe import probe_video
            meta = probe_video(path)
            assert abs(meta['duration']-target) < .12
            samples = array.array('f')
            samples.frombytes(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-f','f32le','-']))
            peak = max(abs(v) for v in samples)
            assert peak < 1
            if suffix:
                assert path.stat().st_size < 20_000_000
            verification[path.name] = dict(decoded=True, peak=peak, metadata=meta,
                bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for kind in ('sam', 'reaction'):
            entries = evidence['sam' if kind == 'sam' else 'reactions']
            for index, event in enumerate(entries):
                path = out/'qa'/f'{name}_{kind}_{index}.jpg'
                img = Image.open(path).convert('RGB')
                img.thumbnail((480, 400))
                cell = Image.new('RGB', (500, 460), '#17191e')
                cell.paste(img, ((500-img.width)//2, 0))
                draw = ImageDraw.Draw(cell)
                draw.text((8, 410), f'{name} {kind} {index+1}', fill='white')
                detail = (('accepted' if event['accepted'] else 'SKIPPED: '+next(
                    m.split('skipped: ')[-1] for m in event['warnings'] if 'spotlight skipped' in m))
                    if kind == 'sam' else event['speaker'])
                draw.text((8, 433), detail, fill='white')
                cells.append(cell)
    sheet = Image.new('RGB', (2000, 460*((len(cells)+3)//4)), '#17191e')
    for index, cell in enumerate(cells):
        sheet.paste(cell, ((index%4)*500, (index//4)*460))
    sheet.save(out/'contact_sheet.jpg', quality=92)
    # Deterministic illustration of the accepted compositor, alongside real skip QA.
    import cv2
    import numpy as np
    from sam.effects import composite
    frame = np.full((360, 640, 3), (85, 115, 145), np.uint8)
    mask = np.zeros((360, 640), np.uint8)
    cv2.ellipse(mask, (320, 190), (24, 48), 0, 0, 360, 1, -1)
    frame[mask > 0] = (100, 170, 100)
    cv2.imwrite(str(out/'synthetic_spotlight.jpg'), np.concatenate([frame, composite(frame, mask, 'spotlight')], axis=1))
    (out/'verification.json').write_text(json.dumps(verification, indent=2))
    print(json.dumps(verification, indent=2), flush=True)


if __name__ == '__main__':
    main()
