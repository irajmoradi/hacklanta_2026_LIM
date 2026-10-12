"""Bounded frame sampling and optional local OCR; never calls a paid service."""
from dataclasses import dataclass
import csv
import io
import math
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Callable, Sequence

from .registry import Box, contains_phrase, get_profile, list_profiles


@dataclass(frozen=True)
class OCRToken:
    """A word or line with a normalized bounding box and confidence in [0, 1]."""
    text: str
    box: Box
    confidence: float = 1.0

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError("OCR confidence must be in [0, 1]")


def _inside(token: OCRToken, region: Box, width: int, height: int) -> bool:
    left, top, right, bottom = region.pixels(width, height)
    x, y = (token.box.x1 + token.box.x2)*width/2, (token.box.y1 + token.box.y2)*height/2
    return left <= x < right and top <= y < bottom


def detect_frames(frames: Sequence[tuple[int, int, Sequence[OCRToken]]]) -> tuple[str, float]:
    """Score OCR phrases plus HUD text placement. No image/model dependencies.

    Each tuple is (width, height, tokens). Repetition across frames supports a
    candidate, but repeating the same phrase within one frame cannot inflate it.
    Confidence is a heuristic evidence score, not a calibrated probability.
    """
    scores = {name: [] for name in list_profiles() if name != "generic"}
    for width, height, tokens in frames:
        if width <= 0 or height <= 0:
            raise ValueError("Frame dimensions must be positive")
        tokens = [t for t in tokens if t.confidence >= .45]
        for name in scores:
            profile = get_profile(name)
            evidence = 0.0
            for region_name, phrases in profile.detection_keywords.items():
                region = profile.regions[region_name]
                # Join words only inside this region, preserving OCR reading order.
                located = " ".join(t.text for t in tokens if _inside(t, region, width, height))
                all_text = " ".join(t.text for t in tokens)
                best = 0.0
                for phrase in phrases:
                    weak = phrase in {"respawn in", "killed by", "eliminado por", "ace"}
                    if contains_phrase(located, phrase):
                        best = max(best, 2.7 if weak else 3.5)
                    elif contains_phrase(all_text, phrase):
                        best = max(best, .3)
                evidence += best
            # A numeric health HUD and top score text are weak layout evidence,
            # never enough to identify a game without a regional keyword.
            if evidence >= 2.7:
                for region_name in ("health", "round_score"):
                    if any(any(c.isdigit() for c in t.text) and _inside(t, profile.regions[region_name], width, height) for t in tokens):
                        evidence += .2
            scores[name].append(evidence)
    ranked = sorted(((max(values, default=0) + min(.6, .2*max(0, sum(v >= 2.7 for v in values)-1)), name)
                     for name, values in scores.items()), reverse=True)
    score, name = ranked[0]
    margin = score - ranked[1][0]
    if score < 2.7 or margin < 1:
        return "generic", 0.0
    return name, round(min(.98, .5 + .35*margin/score + .1*min(1, score/7)), 3)


def _size(png: bytes) -> tuple[int, int]:
    if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
        raise ValueError("Expected a PNG frame")
    return struct.unpack(">II", png[16:24])


def tesseract_ocr(png: bytes, *, language: str = "eng") -> list[OCRToken]:
    """Optional executable integration; missing binary/language pack returns []."""
    if not shutil.which("tesseract"):
        return []
    width, height = _size(png)
    try:
        result = subprocess.run(["tesseract", "stdin", "stdout", "-l", language, "--psm", "11", "tsv"],
                                input=png, capture_output=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        return []
    tokens = []
    for row in csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t"):
        if not row.get("text", "").strip():
            continue
        try:
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            tokens.append(OCRToken(row["text"], Box(x/width, y/height, (x+w)/width, (y+h)/height), float(row["conf"])/100))
        except (ValueError, KeyError):
            continue
    return tokens


def detect_game(video_path: str | Path, *, sample_count: int = 5,
                ocr: Callable[[bytes], Sequence[OCRToken]] | None = None,
                vlm_fallback: Callable[[Sequence[bytes]], tuple[str, float]] | None = None,
                language: str = "eng") -> tuple[str, float]:
    """Sample up to eight PNG frames across a video and return (name, confidence).

    Missing ffmpeg/Tesseract and undecodable video degrade to ('generic', 0.0).
    A missing input file or invalid configuration is a caller error. The optional
    fallback receives sampled PNG bytes only when local evidence is inconclusive;
    callers own its network policy/budget. Hook exceptions propagate to callers.
    """
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or not 1 <= sample_count <= 8:
        raise ValueError("sample_count must be an integer in [1, 8]")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return "generic", 0.0
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path.resolve())], capture_output=True, timeout=20, check=True)
        duration = float(probe.stdout)
        if not math.isfinite(duration) or duration <= 0:
            return "generic", 0.0
    except (ValueError, OSError, subprocess.SubprocessError):
        return "generic", 0.0
    images, frames = [], []
    reader = ocr if ocr is not None else lambda png: tesseract_ocr(png, language=language)
    for index in range(sample_count):
        timestamp = duration*(index+.5)/sample_count
        try:
            result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(path.resolve()),
                                     "-frames:v", "1", "-vf", "scale=w='min(1280,iw)':h=-1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                                    capture_output=True, timeout=30, check=True)
            width, height = _size(result.stdout)
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
        images.append(result.stdout)
        frames.append((width, height, reader(result.stdout)))
    detected = detect_frames(frames)
    if detected[0] == "generic" and images and vlm_fallback is not None:
        name, confidence = vlm_fallback(tuple(images))
        if name not in list_profiles() or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Fallback must return a known profile and confidence in [0, 1]")
        return (name, float(confidence)) if name != "generic" else ("generic", 0.0)
    return detected
