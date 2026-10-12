"""Local, profile-specific HUD corroboration on sampled frames."""
import re

import cv2
import numpy as np


def white_mask(frame):
    """Keep bright, low-chroma UI glyphs rather than the scene behind them."""
    low = frame.min(axis=2)
    high = frame.max(axis=2)
    return ((low > 170) & ((high.astype(float) - low) < 65)).astype('uint8') * 255


def layout_evidence(png, profile, reader):
    """Require timer OCR, health OCR, ability slots and minimap together.

    Coordinates live in the profile, so unsupported/custom layouts abstain.
    The returned booleans are evidence, not proof of POV ownership/alive state.
    """
    frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if frame is None or not profile.detection_layout:
        return {}
    h, w = frame.shape[:2]
    def crop(box):
        x1, y1, x2, y2 = box
        return frame[int(y1*h):int(y2*h), int(x1*w):int(x2*w)]
    cues = {}
    for name in ('timer', 'health'):
        region = crop(profile.detection_layout[name])
        mask = white_mask(cv2.resize(region, None, fx=3, fy=3))
        mask = cv2.copyMakeBorder(255-mask, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        ok, encoded = cv2.imencode('.png', mask)
        text = ' '.join(t.text for t in reader(encoded.tobytes()) if t.confidence >= .4) if ok else ''
        pattern = r'\b[0-2]:[0-5][0-9]\b' if name == 'timer' else r'\b(?:100|[1-9][0-9]?)\b'
        cues[name] = bool(re.search(pattern, text))
    slots = [white_mask(crop(box)).mean()/255 for box in profile.detection_layout['abilities']]
    cues['abilities'] = bool(sum(.025 < fraction < .65 for fraction in slots) >= 3)
    minimap = crop(profile.detection_layout['minimap'])
    edges = cv2.Canny(cv2.cvtColor(minimap, cv2.COLOR_BGR2GRAY), 80, 160)
    # A minimap contains many crisp polygon boundaries, unlike a blank corner.
    cues['minimap'] = bool(.025 < np.mean(edges)/255 < .3)
    from signals.ocr import valorant_rows
    if profile.name == 'valorant':
        box = profile.regions['kill_feed']
        cues['kill_feed'] = bool(valorant_rows(crop((box.x1, box.y1, box.x2, box.y2))))
    return cues
