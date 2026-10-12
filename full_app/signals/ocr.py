"""Optional local Tesseract HUD recognition; no models are downloaded."""

import re
import shutil
import subprocess
import warnings

import cv2
import numpy as np


# Normalized (left, top, right, bottom). Override for resolution/UI scaling.
PROFILES = {
    "auto": {"kill_feed": (.62, .02, 1., .32), "banner": (.20, .35, .80, .75)},
    "valorant": {"kill_feed": (.64, .03, 1., .30), "banner": (.25, .42, .75, .80)},
    "overwatch2": {"kill_feed": (.64, .02, 1., .30), "banner": (.23, .43, .77, .75)},
    "deadlock": {"kill_feed": (.62, .03, 1., .33), "banner": (.20, .35, .80, .75)},
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


class HUDReader:
    def __init__(self, regions: dict, cooldown: float):
        self.regions = regions
        self.cooldown = cooldown
        self.last_seen = {}
        self.previous = {}
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
            kind, text = classify(result.stdout.decode("utf-8", errors="replace"))
            if kind:
                key = (name, kind, text)
                last = self.last_seen.get(key, -float("inf"))
                self.last_seen[key] = timestamp
                if timestamp - last >= self.cooldown:
                    events.append({"time": round(timestamp, 3), "type": kind,
                                   "text": text, "region": name})
        return events
