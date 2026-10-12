"""Render private reaction QA artifacts on gameplay; never commit the outputs."""
import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .pack import load_pack
from .render import render_overlay


def _frame(path, at):
    capture = cv2.VideoCapture(str(path))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, at*1000)
        ok, result = capture.read()
        if not ok:
            raise RuntimeError(f'Cannot read QA frame from {path}')
        return result
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--gameplay', type=Path, help='Existing authorized gameplay, otherwise synthetic testsrc2')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    chosen = {}
    for reaction in load_pack(args.pack):
        chosen.setdefault(reaction.speaker, reaction)
    results = []
    for preset, dimensions in [('landscape', '640:360'), ('vertical', '360:640'), ('square', '480:480')]:
        for brightness, level in [('dark', '-0.20'), ('bright', '0.20')]:
            base = args.output/f'{preset}-{brightness}-base.mp4'
            command = ['ffmpeg', '-v', 'error', '-y', '-threads', '1']
            if args.gameplay:
                command += ['-ss', '1', '-i', str(args.gameplay)]
            else:
                command += ['-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=25:d=3']
            command += ['-t', '3', '-an', '-vf',
                        f'scale={dimensions}:force_original_aspect_ratio=increase,crop={dimensions},eq=brightness={level}',
                        '-c:v', 'libx264', '-threads', '2', '-pix_fmt', 'yuv420p', str(base)]
            subprocess.run(command, check=True)
            for speaker, reaction in chosen.items():
                target = args.output/f'{reaction.id}-{preset}-{brightness}.mp4'
                # The renderer refuses overwrites; QA also leaves previous results intact.
                if target.exists():
                    raise FileExistsError(target)
                render_overlay(base, reaction, preset, peak_time=.6, show_speaker=True, output_path=target)
                at = .6+min(reaction.duration/2, .4)
                original, after = _frame(base, at), _frame(target, at)
                source = _frame(reaction.file, min(reaction.duration/2, .4))
                height = original.shape[0]
                source = cv2.resize(source, (height, height))
                sheet = np.concatenate((source, original, after), axis=1)
                cv2.imwrite(str(target.with_suffix('.jpg')), sheet)
                results.append({'speaker': speaker, 'preset': preset, 'background': brightness,
                                'clip': reaction.id, 'video': target.name, 'still': target.with_suffix('.jpg').name})
                print(target, flush=True)
    (args.output/'qa.json').write_text(json.dumps(results, indent=2)+'\n')


if __name__ == '__main__':
    main()
