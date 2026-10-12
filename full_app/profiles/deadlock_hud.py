"""Deadlock's souls economy and four-lane HUD, calibrated on 16:9 footage.

Lazy-loaded by the optional visual fallback; no models or network access.
"""
import re

import cv2
import numpy as np


def evidence(frame, layout, reader):
    height, width = frame.shape[:2]

    def crop(name):
        x1, y1, x2, y2 = layout[name]
        return frame[int(y1*height):int(y2*height), int(x1*width):int(x2*width)]

    def text(name):
        region = cv2.resize(crop(name), None, fx=3, fy=3)
        ok, png = cv2.imencode('.png', region)
        return ' '.join(t.text for t in reader(png.tobytes()) if t.confidence >= .4) if ok else ''

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
    lanes = sum(np.mean(colorful & (hue >= lo) & (hue <= hi)) > .003
                for lo, hi in ((20, 38), (5, 19), (85, 115), (125, 165)))
    team = cv2.cvtColor(crop('team_bar'), cv2.COLOR_BGR2HSV)
    # Six portrait badges per side and two differently colored soul totals.
    blocks = np.array_split(team, 12, axis=1)
    badges = sum(np.mean((b[:, :, 1] > 90) & (b[:, :, 2] > 110)) > .08 for b in blocks)
    return dict(timer=timer, souls=souls, minimap=bool(lanes == 4), team_bar=bool(badges >= 9))
