"""Deadlock's souls economy and four-lane HUD, calibrated on 16:9 footage.

Lazy-loaded by the optional visual fallback; no models or network access.
"""
import re

import cv2
import numpy as np


def evidence(frame, layout, reader):
    # HUD patches moved the souls counter and replaced four lanes with three.
    # Require a complete layout, never combine unrelated cues across variants.
    candidates = [_evidence(frame, layout, reader)]
    for variant in layout.get('variants', []):
        candidates.append(_evidence(frame, {**layout, **variant}, reader))
    return max(candidates, key=lambda cues: sum(cues.values()))


def _evidence(frame, layout, reader):
    height, width = frame.shape[:2]

    def crop(name):
        x1, y1, x2, y2 = layout[name]
        return frame[int(y1*height):int(y2*height), int(x1*width):int(x2*width)]

    def text(name):
        region = cv2.resize(crop(name), None, fx=3, fy=3)
        ok, png = cv2.imencode('.png', region)
        raw = ' '.join(t.text for t in reader(png.tobytes()) if t.confidence >= .4) if ok else ''
        if name == 'timer' and layout.get('mask_timer'):
            if re.search(r'\b\d{1,2}:[0-5]\d\b', raw):
                return raw
            from .hud import white_mask
            region = cv2.copyMakeBorder(255-white_mask(region), 12, 12, 12, 12,
                                       cv2.BORDER_CONSTANT, value=255)
            ok, png = cv2.imencode('.png', region)
            return ' '.join(t.text for t in reader(png.tobytes()) if t.confidence >= .4) if ok else ''
        return raw

    timer = bool(re.search(r'\b\d{1,2}:[0-5]\d\b', text('timer')))
    souls_text = text('souls')
    mint = cv2.cvtColor(crop('souls'), cv2.COLOR_BGR2HSV)
    mint_fraction = np.mean((mint[:, :, 0] > 65) & (mint[:, :, 0] < 90) &
                            (mint[:, :, 1] > 45) & (mint[:, :, 2] > 150))
    souls = bool(re.search(r'\bSOULS\b', souls_text, re.I) or
                 (re.search(r'\b\d[\d,]*\b', souls_text) and mint_fraction > .025))
    minimap = cv2.cvtColor(crop('minimap'), cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(minimap)
    # Yellow, orange, blue and purple lanes together distinguish the MOBA map
    # from Valorant's upper-left minimap and League's lower-right three lanes.
    colorful = (sat > 100) & (val > 130)
    lane_hues = layout.get('lane_hues', ((20, 38), (5, 19), (85, 115), (125, 165)))
    lanes = sum(np.mean(colorful & (hue >= lo) & (hue <= hi)) > .003
                for lo, hi in lane_hues)
    team = cv2.cvtColor(crop('team_bar'), cv2.COLOR_BGR2HSV)
    # Six portrait badges per side and two differently colored soul totals.
    blocks = np.array_split(team, 12, axis=1)
    badges = sum(np.mean((b[:, :, 1] > 90) & (b[:, :, 2] > 110)) > .08 for b in blocks)
    return dict(timer=timer, souls=souls, minimap=bool(lanes == len(lane_hues)), team_bar=bool(badges >= 9))
