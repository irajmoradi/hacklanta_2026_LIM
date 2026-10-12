"""Offline full-source measurement. Run with PYTHONPATH=full_app; no API calls.

Only event types/timestamps are persisted, never OCR participant names.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time
import warnings

from profiles import detect_game
from profiles.detection import tesseract_ocr
from signals.detector import _probe, _video
from signals.models import Config
from signals.ocr import regions_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('video', type=Path)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--detect-only', action='store_true')
    args = parser.parse_args()
    os.environ['OMP_THREAD_LIMIT'] = '1'
    warnings.filterwarnings('error', message='OCR failed; disabling OCR:.*', category=RuntimeWarning)
    started = time.monotonic()
    name, confidence = detect_game(args.video, **({'ocr': tesseract_ocr} if args.baseline else {}))
    print(json.dumps(dict(profile=name, confidence=confidence, detection_seconds=round(time.monotonic()-started, 2))), flush=True)
    if args.detect_only:
        return
    duration, stream, _ = _probe(args.video)
    config = Config(ocr=True, sample_fps=2, ocr_interval=2, scene_backend='ffmpeg')
    _, _, events = _video(args.video, duration, stream, config, regions_for(name))
    print(json.dumps(dict(duration=duration, counts=Counter(e['type'] for e in events),
                         events=[{k: e[k] for k in ('time', 'type', 'region') if k in e}
                                 for e in events if e['type'] != 'scene_cut'],
                         elapsed=round(time.monotonic()-started, 2))), flush=True)


if __name__ == '__main__':
    main()
