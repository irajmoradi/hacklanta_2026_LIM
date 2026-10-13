"""Decode, size/audio/duration checks and hit-moment contact sheets."""
import array
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

OUT = Path('/srv/demo_out/style1')


def main():
    report = {}
    tiles = []
    for name, expected in [('mean_vertical',30), ('landscape',60), ('cinematic',30), ('clean',30)]:
        first_tile = len(tiles)
        plan = json.loads((OUT/f'planned_{name}.json').read_text())['planner_plan']
        for suffix in ('', '_discord'):
            path = OUT/f'montage_{name}{suffix}.mp4'
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'], check=True)
            info = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))
            duration = float(info['format']['duration'])
            assert abs(duration-expected) < .12, duration
            assert not suffix or path.stat().st_size < 20_000_000
            raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-f','f32le','-'])
            samples = array.array('f')
            samples.frombytes(raw)
            peak = max(map(abs, samples))
            assert peak < 1, peak
            report[name+suffix] = dict(bytes=path.stat().st_size, duration=duration, peak=peak,
                                       sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for i, clip in enumerate(plan['clips']):
            # Actual event hit and its aftermath, not arbitrary montage timestamps.
            for phase, offset in [('hit',0), ('after',.3)]:
                at = min(clip['start']+clip['duration']-.05, clip['peak']+offset)
                frame = OUT/f'{name}_{i}_{phase}.png'
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(at),'-i',str(OUT/f'montage_{name}.mp4'),
                                '-frames:v','1',str(frame)],check=True)
                im = Image.open(frame).convert('RGB')
                im.thumbnail((480,360))
                tile = Image.new('RGB',(500,420),'#171923')
                tile.paste(im,((500-im.width)//2,30))
                d = ImageDraw.Draw(tile)
                d.text((10,8),f'{name} / {clip["id"]} / {phase} @ {at:.2f}',fill='white')
                names = [e['name'] for e in plan['effects'] if e['clip_id']==clip['id'] and e['start']<=at<e['start']+e['duration']]
                d.text((10,392),', '.join(names)[:77],fill='white')
                tiles.append(tile)
        individual = tiles[first_tile:]
        sheet = Image.new('RGB', (1500, 420*((len(individual)+2)//3)), '#171923')
        for i, tile in enumerate(individual):
            sheet.paste(tile, ((i%3)*500, (i//3)*420))
        sheet.save(OUT/f'contact_sheet_{name}.jpg', quality=90)
    sheet = Image.new('RGB',(1500,420*((len(tiles)+2)//3)),'#171923')
    for i,tile in enumerate(tiles):
        sheet.paste(tile,((i%3)*500,(i//3)*420))
    sheet.save(OUT/'contact_sheet.jpg', quality=90)
    (OUT/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
