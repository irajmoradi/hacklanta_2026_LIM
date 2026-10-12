"""Opt-in offline full-VOD measurement (no keys, network or provider calls).

Run from repo root: PYTHONPATH=full_app python full_app/tests/measure_fix5.py VIDEO
Print aggregate counts only: OCR player names are deliberately not persisted.
"""
import json
import os
import sys
import time
import warnings
from collections import Counter
from profiles import detect_game
from profiles.detection import tesseract_ocr
from signals.detector import _probe, _video
from signals.models import Config
from signals.ocr import regions_for
from pathlib import Path


if __name__ == '__main__':
    # Avoid OpenMP oversubscription on the shared runner. A timed-out reader
    # must not silently produce a misleading "full VOD" detection count.
    os.environ['OMP_THREAD_LIMIT'] = '1'
    warnings.filterwarnings('error', message='OCR failed; disabling OCR:.*', category=RuntimeWarning)
    path = Path(sys.argv[1])
    started = time.monotonic()
    baseline = '--baseline' in sys.argv[2:]
    # Injecting the original full-frame reader disables the new layout pass.
    # Generic regions and keyword-only parsing are unchanged from DEMO-02.
    profile, confidence = detect_game(path, **({'ocr': tesseract_ocr} if baseline else {}))
    print(json.dumps(dict(profile=profile, confidence=confidence)), flush=True)
    duration, stream, _ = _probe(path)
    config = Config(ocr=True, sample_fps=2, ocr_interval=2, scene_backend='ffmpeg')
    _, _, events = _video(path, duration, stream, config, regions_for(profile))
    counts = Counter(e['type'] for e in events)
    print(json.dumps(dict(duration=duration, events=counts, ocr_interval=config.ocr_interval,
                          ocr_width=config.ocr_width, elapsed=round(time.monotonic()-started, 2))), flush=True)
