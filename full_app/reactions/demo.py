"""Generate fictitious avatars only: python -m reactions.demo [output-folder]."""
import argparse
import json
import subprocess
from pathlib import Path


def generate_pack(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (speaker, label, color) in enumerate([
            ('Dot', 'sick_kill', '0x3299EE'), ('Bop', 'sick_kill', '0xEE7733'),
            ('Dot', 'wholesome', '0x3299EE'), ('Bop', 'roast', '0xEE7733')]):
        filename = f'demo_{index}.mp4'
        # Circle silhouette and oscillating mouth made entirely by FFmpeg.
        vf = (f"format=rgb24,geq=r='if(lte(pow(X-80,2)+pow(Y-80,2),3600),{int(color[2:4],16)},255)':"
              f"g='if(lte(pow(X-80,2)+pow(Y-80,2),3600),{int(color[4:6],16)},255)':"
              f"b='if(lte(pow(X-80,2)+pow(Y-80,2),3600),{int(color[6:8],16)},255)',"
              "drawbox=x=55:y=58:w=8:h=8:color=black:t=fill,"
              "drawbox=x=97:y=58:w=8:h=8:color=black:t=fill,"
              "geq=r='if(between(X,60,100)*lt(abs(Y-105),3+8*abs(sin(T*15))),0,r(X,Y))':"
              "g='if(between(X,60,100)*lt(abs(Y-105),3+8*abs(sin(T*15))),0,g(X,Y))':"
              "b='if(between(X,60,100)*lt(abs(Y-105),3+8*abs(sin(T*15))),0,b(X,Y))'")
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=white:s=160x160:r=25:d=1',
                        '-f', 'lavfi', '-i', f'sine=frequency={880+index*100}:duration=1:sample_rate=48000',
                        '-filter_threads', '1', '-vf', vf, '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-shortest', str(folder / filename)], check=True)
        entries.append(dict(id=f'demo_{index}', speaker=speaker, label=label, text='Beep!',
                            file=filename, duration=1.0, background='light'))
    (folder / 'pack.json').write_text(json.dumps({'version': 1, 'clips': entries}, indent=2), encoding='utf-8')
    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', default='reaction_packs/synthetic')
    generate_pack(parser.parse_args().folder)
