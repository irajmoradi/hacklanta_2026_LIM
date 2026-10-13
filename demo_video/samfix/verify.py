"""Decode every output and build a contact sheet of every SAM attempt/reaction."""
import array
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'full_app'))


def head_measurements(job):
    """Project real matte extents through the renderer's crop, scale and edge clip."""
    import cv2
    import math
    import numpy as np
    from reactions import load_pack
    from reactions.render import layout, matte_bounds, visible_matte
    pack = {r.id: r for r in load_pack('/srv/packs/team')}
    preset = job['options']['preset']
    width, height = (1920, 1080) if preset == 'landscape' else (1080, 1920)
    side, _, _ = layout(width, height, preset)
    measurements = []
    for event in job['render_evidence']['reactions']:
        reaction = pack[event['id']]
        matte = Path(reaction.alpha_file or reaction.mask_file)
        left, top, right, bottom = matte_bounds(str(matte), matte.stat().st_mtime_ns, bool(reaction.alpha_file))
        cap = cv2.VideoCapture(str(reaction.mask_file))
        delta = min(.5, event['duration']/2)
        cap.set(cv2.CAP_PROP_POS_MSEC, delta*1000)
        ok, frame = cap.read()
        cap.release()
        assert ok
        mask = visible_matte(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)[None, ...])
        ys, xs = np.nonzero(mask)
        sh, sw = mask.shape
        ratio = sw*(right-left)/(sh*(bottom-top))
        hw = side if preset == 'vertical' else max(2, round(side*ratio/2)*2)
        hh = max(2, round(side/ratio/2)*2) if preset == 'vertical' else side
        margin = max(2, int(side*.025))
        x, y = width-hw+margin, height-hh+margin
        # The sampled reaction frames are past the bounce/fade-in interval.
        y += hh*.018*math.sin(2*math.pi*delta/2.4)
        visible_w = max(0, min(width, x+((xs.max()+1)/sw-left)/(right-left)*hw)
                        -max(0, x+(xs.min()/sw-left)/(right-left)*hw))
        visible_h = max(0, min(height, y+((ys.max()+1)/sh-top)/(bottom-top)*hh)
                        -max(0, y+(ys.min()/sh-top)/(bottom-top)*hh))
        fraction = visible_w/width if preset == 'vertical' else visible_h/height
        low, high = (.22, .28) if preset == 'vertical' else (.28, .35)
        assert low <= fraction <= high, (preset, reaction.id, fraction)
        measurements.append(dict(id=reaction.id, speaker=reaction.speaker,
                                 visible_fraction=round(fraction, 4),
                                 axis='width' if preset == 'vertical' else 'height'))
    return measurements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', choices=['landscape', 'mean_vertical'])
    args = parser.parse_args()
    out = Path('/srv/demo_out/samfix')
    cells, verification, heads = [], {}, {}
    label_font = ImageFont.load_default(size=18)
    for name, target in [('landscape', 60), ('mean_vertical', 30)]:
        if args.only and name != args.only:
            continue
        job = json.loads((out/f'job_{name}.json').read_text())
        assert not job['options']['privacy']
        evidence = job['render_evidence']
        assert len({r['speaker'] for r in evidence['reactions']}) == 4
        assert len(job['samfix_attempts']) == 3
        heads[name] = head_measurements(job)
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
            assert peak < 1, (path.name, peak)
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
                draw.text((8, 410), f'{name} {kind} {index+1}', fill='white', font=label_font)
                detail = (('accepted' if event['accepted'] else 'SKIPPED: '+next(
                    m.split('skipped: ')[-1] for m in event['warnings'] if 'spotlight skipped' in m))
                    if kind == 'sam' else event['speaker'])
                draw.text((8, 433), detail, fill='white', font=label_font)
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
    (out/'head_measurements.json').write_text(json.dumps(heads, indent=2))
    (out/'SHA256SUMS').write_text(''.join(f"{v['sha256']}  {name}\n" for name,v in verification.items()))
    print(json.dumps(verification, indent=2), flush=True)


if __name__ == '__main__':
    main()
