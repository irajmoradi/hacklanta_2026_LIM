"""Optional local Tesseract HUD recognition; no models are downloaded."""

import re
import shutil
import subprocess
import warnings
from difflib import SequenceMatcher

import cv2
import numpy as np


# Normalized (left, top, right, bottom). Override for resolution/UI scaling.
PROFILES = {
    "auto": {"kill_feed": (.62, .02, 1., .32), "banner": (.20, .35, .80, .75)},
    "valorant": {"kill_feed": (.64, .08, 1., .32), "banner": (.25, .15, .75, .40)},
    "overwatch2": {"kill_feed": (.64, .02, 1., .30), "banner": (.23, .43, .77, .75)},
    "deadlock": {"kill_feed": (.025, .18, .36, .45), "banner": (.20, .125, .84, .30),
                 "death_banner": (.36, .70, .68, .94), "souls": (.012, .85, .13, .907)},
}


PROFILES["generic"] = dict(PROFILES["auto"])
PROFILES["leagueoflegends"] = {"kill_feed": (.75, .15, 1., .60), "banner": (.25, .15, .75, .4)}


def regions_for(profile: str, overrides: dict | None = None) -> dict:
    key = profile.lower().replace(" ", "").replace("_", "").replace("-", "")
    if key not in PROFILES:
        raise ValueError(f"unknown game profile: {profile}")
    regions = dict(PROFILES[key] if overrides is None else overrides)
    for name, box in regions.items():
        if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise ValueError(f"invalid normalized OCR region: {name}")
    return regions


def classify(text: str) -> tuple[str | None, str]:
    text = " ".join(text.upper().split())
    if re.search(r"\b(KILLED BY|ELIMINATED BY|YOU DIED|DEFEATED BY)\b", text):
        return "death", text
    if re.search(r"\b(ELIMINATED|KILLED|KILL|DOUBLE KILL|TRIPLE KILL)\b", text):
        return "kill", text
    return None, text


def valorant_rows(crop):
    """Locate paired red/teal feed bars, excluding the score strip above them."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    red = ((hue < 10) | (hue > 170)) & (sat > 70) & (val > 80)
    teal = (hue > 65) & (hue < 95) & (sat > 55) & (val > 80)
    # Either team can be the killer; both colored ends must share a row.
    active = (red.sum(axis=1) > crop.shape[1]*.10) & (teal.sum(axis=1) > crop.shape[1]*.10)
    indices = np.flatnonzero(active)
    if not len(indices):
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 3) + 1)
    rows = []
    scale = crop.shape[1] / (1920*.36)
    for group in groups:
        top, bottom = int(group[0]), int(group[-1])+1
        if not 16*scale <= bottom-top <= 48*scale:
            continue
        columns = np.flatnonzero((red[top:bottom] | teal[top:bottom]).sum(axis=0) > (bottom-top)*.4)
        if len(columns) and columns[-1]-columns[0] > crop.shape[1]*.45:
            rows.append(crop[max(0, top-1):min(len(crop), bottom+1), columns[0]:columns[-1]+1])
    return rows


def feed_text(text):
    """A weapon glyph is not an English kill keyword: require two name tokens."""
    words = re.findall(r'[A-Za-z0-9]{3,}', text.upper())
    names = [word for word in words if sum(c.isalpha() for c in word) >= 3]
    return ' '.join(names) if len(names) >= 2 else None


def deadlock_rows(crop):
    """Find Deadlock's upper-left cream/red participant panels on the same row."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    cream = (hue >= 15) & (hue <= 40) & (sat < 85) & (val > 190)
    red = ((hue < 10) | (hue > 170)) & (sat > 100) & (val > 150)
    active = (cream.sum(axis=1) > crop.shape[1]*.10) & (red.sum(axis=1) > crop.shape[1]*.07)
    indices = np.flatnonzero(active)
    if not len(indices):
        return []
    rows = []
    scale = crop.shape[1] / (1920*.335)
    for group in np.split(indices, np.flatnonzero(np.diff(indices) > max(3, np.ceil(10*scale))) + 1):
        top, bottom = int(group[0]), int(group[-1])+1
        if not 20*scale <= bottom-top <= 45*scale:
            continue
        columns = np.flatnonzero((cream[top:bottom] | red[top:bottom]).sum(axis=0) > (bottom-top)*.35)
        if len(columns) and columns[-1]-columns[0] > crop.shape[1]*.25:
            rows.append(crop[max(0, top-1):min(len(crop), bottom+1), columns[0]:columns[-1]+1])
    return rows


def classify_deadlock(text, region):
    """HUD evidence only; persistent objectives/ability labels are not outcomes."""
    text = ' '.join(text.upper().split())
    if region == 'death_banner':
        return ('death' if re.search(r'\b(RESPAWN IN|YOU DIED|KILLED BY)\b', text) else None), text
    if re.search(r'\b(?:GUARDIAN|WALKER|PATRON|SHRINE)\b', text):
        return ('objective_taken' if re.search(r'\b(DESTROYED|DEFEATED)\b', text) else None), text
    if re.search(r'\bURN DELIVERED\b', text):
        return 'objective_taken', text
    return classify(text)


def same_feed_event(left, right):
    # Match both participants independently: a long killer name must not hide
    # a different victim in a rapid multikill. Middle OCR weapon noise is ignored.
    a, b = left.split(), right.split()
    return all(SequenceMatcher(None, x, y).ratio() >= .72 for x, y in ((a[0], b[0]), (a[-1], b[-1])))


class HUDReader:
    def __init__(self, regions: dict, cooldown: float):
        self.regions = regions
        self.cooldown = cooldown
        self.last_seen = {}
        self.previous = {}
        self.feed_seen = {}
        self.souls_previous = None
        self.executable = shutil.which("tesseract")
        if not self.executable:
            warnings.warn("Tesseract is unavailable; continuing without OCR", RuntimeWarning)

    def read(self, frame: np.ndarray, timestamp: float) -> list[dict]:
        if not self.executable:
            return []
        height, width = frame.shape[:2]
        events = []
        for name, (x1, y1, x2, y2) in self.regions.items():
            crop = frame[int(y1 * height):max(int(y1 * height) + 1, int(y2 * height)),
                         int(x1 * width):max(int(x1 * width) + 1, int(x2 * width))]
            deadlock = self.regions == PROFILES['deadlock']
            if name == 'kill_feed' and (self.regions == PROFILES['valorant'] or deadlock):
                events.extend(self._feed(crop, timestamp, deadlock=deadlock))
                if not self.executable:
                    return events
                continue
            # Identical/static HUDs do not need repeated OCR subprocesses.
            small = cv2.resize(crop, (96, 32))
            previous = self.previous.get(name)
            self.previous[name] = small
            if previous is not None and cv2.absdiff(previous, small).mean() < 1.0:
                continue
            crop = cv2.resize(crop, None, fx=2, fy=2)
            ok, png = cv2.imencode(".png", crop)
            if not ok:
                continue
            try:
                result = subprocess.run(
                    [self.executable, "stdin", "stdout", "--psm", "6", "-l", "eng"],
                    input=png.tobytes(), capture_output=True, timeout=10, check=True,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                warnings.warn(f"OCR failed; disabling OCR: {exc}", RuntimeWarning)
                self.executable = None
                return events
            raw = result.stdout.decode("utf-8", errors="replace")
            if deadlock and name == 'souls':
                # Economy changes are ambiguous (creeps, kills, objectives or
                # item purchases). Never promote this into a confirmed kill.
                match = re.search(r'(?<!\w)\d[\d,]*(?!\w)', raw)
                if match:
                    value = int(match.group().replace(',', ''))
                    previous = self.souls_previous
                    self.souls_previous = (timestamp, value)
                    if previous and 0 < timestamp-previous[0] <= 5 and 300 <= value-previous[1] <= 5000:
                        events.append(dict(time=round(timestamp, 3), type='souls_gain',
                                           amount=value-previous[1], region=name, attribution='unknown'))
                continue
            kind, text = classify_deadlock(raw, name) if deadlock else classify(raw)
            if kind:
                key = (name, kind, text)
                last = self.last_seen.get(key, -float("inf"))
                self.last_seen[key] = timestamp
                if timestamp - last >= self.cooldown:
                    event = {"time": round(timestamp, 3), "type": kind, "text": text, "region": name}
                    if deadlock:
                        event['attribution'] = 'unknown'
                    events.append(event)
        return events

    def _feed(self, crop, timestamp, *, deadlock=False):
        from profiles.hud import white_mask
        events = []
        # Visible rows slide upward and OCR spelling fluctuates. Match identity
        # across row positions and refresh on every sighting, not just emission.
        self.feed_seen = {text: seen for text, seen in self.feed_seen.items()
                          if timestamp-seen <= max(8., self.cooldown)}
        for row in (deadlock_rows(crop) if deadlock else valorant_rows(crop)):
            row = cv2.resize(row, None, fx=max(1., 48/row.shape[0]), fy=max(1., 48/row.shape[0]))
            mask = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY) if deadlock else 255-white_mask(row)
            mask = cv2.copyMakeBorder(mask, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
            ok, png = cv2.imencode('.png', mask)
            if not ok:
                continue
            try:
                result = subprocess.run([self.executable, 'stdin', 'stdout', '--psm', '7', '-l', 'eng'],
                                        input=png.tobytes(), capture_output=True, timeout=10, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                warnings.warn(f'OCR failed; disabling OCR: {exc}', RuntimeWarning)
                self.executable = None
                break
            text = feed_text(result.stdout.decode('utf-8', errors='replace'))
            if not text:
                continue
            kind = 'kill'
            if deadlock and re.search(r'\b(GUARDIAN|WALKER|PATRON|SHRINE|URN)\b', text):
                kind, _ = classify_deadlock(text, 'kill_feed')
                if not kind:
                    continue
            previous = next((key for key in self.feed_seen if same_feed_event(key, text)), None)
            if previous is None:
                events.append({'time': round(timestamp, 3), 'type': kind, 'text': text,
                               'region': 'kill_feed', 'attribution': 'unknown'})
            self.feed_seen[previous or text] = timestamp
        return events
