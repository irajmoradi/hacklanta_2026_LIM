"""Offline audio fingerprint correlation and affine clock fitting."""
import subprocess
from pathlib import Path

from fx.media import probe as probe_media

import numpy as np

from .models import Alignment, normalize

SAMPLE_RATE = 8000
HOP = 40  # 5 ms: finer than a 60 fps frame


class SyncError(ValueError):
    """Recordings have insufficient, ambiguous, or inconsistent shared audio."""


def run(command: list[str], *, timeout: float = 300, cwd: str | Path | None = None) -> bytes:
    result = subprocess.run(command, capture_output=True, timeout=timeout, cwd=cwd)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-2000:])
    return result.stdout


def probe(path: str | Path) -> tuple[float, bool]:
    try:
        data = probe_media(path, timeout=300)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr[-2000:]) from exc
    if not any(s["codec_type"] == "video" for s in data["streams"]):
        raise ValueError(f"No video stream: {path}")
    duration = float(data["format"]["duration"])
    if not np.isfinite(duration) or duration <= 0:
        raise ValueError("Recording duration must be finite and positive")
    return duration, any(s["codec_type"] == "audio" for s in data["streams"])


def _features(path: str | Path) -> np.ndarray:
    _, has_audio = probe(path)
    if not has_audio:
        raise SyncError(f"No audio for synchronization: {path}")
    raw = run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn",
               "-af", "aresample=8000:async=1:first_pts=0", "-ac", "1", "-ar", "8000",
               "-f", "f32le", "pipe:1"])
    samples = np.frombuffer(raw, dtype="<f4")
    if len(samples) < SAMPLE_RATE * 4 or np.max(np.abs(samples)) < 1e-5:
        raise SyncError("Need at least four seconds of non-silent shared audio")
    # Spectral energy is insensitive to waveform polarity and small resampling
    # differences. Independent bands limit interference from voice chat.
    frames = np.lib.stride_tricks.sliding_window_view(samples, 160)[::HOP]
    bands = []
    # Work in chunks to avoid materializing the entire match's STFT.
    for start in range(0, len(frames), 20000):
        spectrum = np.abs(np.fft.rfft(frames[start:start + 20000] * np.hanning(160))) ** 2
        bands.append(np.stack([np.log1p(spectrum[:, lo:hi].sum(axis=1) * 100)
                               for lo, hi in ((4, 10), (10, 20), (20, 40), (40, 79))], axis=1))
    features = np.concatenate(bands)
    variation = np.percentile(features, 90, axis=0) - np.percentile(features, 10, axis=0)
    if np.count_nonzero(variation > .1) < 2:
        raise SyncError("Audio has insufficient changing broadband content")
    # Remove stationary music/hum and normalize independently per band.
    features -= np.median(features, axis=0)
    scale = np.std(features, axis=0)
    if np.max(scale) < 1e-4:
        raise SyncError("Audio has no useful temporal variation")
    return features / np.maximum(scale, 1e-4)


def _match(reference: np.ndarray, query: np.ndarray) -> tuple[int, float] | None:
    """Normalized multiband cross-correlation, all valid reference positions."""
    n, m = len(reference), len(query)
    query = query - query.mean(axis=0)
    size = 1 << (n + m - 2).bit_length()
    corr = np.fft.irfft(np.fft.rfft(reference, size, axis=0) *
                        np.fft.rfft(query[::-1], size, axis=0), size, axis=0)[m - 1:n]
    sums = np.vstack([np.zeros((1, 4)), np.cumsum(reference, axis=0)])
    squares = np.vstack([np.zeros((1, 4)), np.cumsum(reference ** 2, axis=0)])
    energy = squares[m:] - squares[:-m] - (sums[m:] - sums[:-m]) ** 2 / m
    denom = np.sqrt(np.maximum(energy, 0) * np.sum(query ** 2, axis=0))
    scores = np.mean(corr / np.maximum(denom, 1e-9), axis=1)
    peak = int(np.argmax(scores))
    confidence = float(scores[peak])
    # Repeated/periodic audio must not fabricate an arbitrary offset.
    competitors = scores.copy()
    competitors[max(0, peak - 40):peak + 41] = -1
    if confidence < .30 or confidence - np.max(competitors) < .025:
        return None
    return peak, confidence


def _align(reference: np.ndarray, other: np.ndarray) -> Alignment:
    window = 400  # two seconds: tolerate slight clock drift within each match
    points = []
    for start in np.unique(np.linspace(0, len(other) - window, 19).astype(int)):
        match = _match(reference, other[start:start + window])
        if match:
            peak, confidence = match
            points.append(((start + window / 2) * .005,
                           (peak + window / 2) * .005, confidence))
    if len(points) < 3:
        raise SyncError("Fewer than three unambiguous shared audio windows")
    points = np.asarray(points)
    x, y = points[:, 0], points[:, 1]
    # RANSAC over all pairs, deterministic and tolerant of unrelated speech.
    best = None
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            if x[j] - x[i] < 2:
                continue
            rate = (y[j] - y[i]) / (x[j] - x[i])
            if not .98 <= rate <= 1.02:
                continue
            mask = np.abs(y - (rate * x + y[i] - rate * x[i])) <= .025
            if best is None or mask.sum() > best.sum():
                best = mask
    if best is None or best.sum() < max(3, len(points) * .5):
        raise SyncError("Shared audio does not support a consistent clock (maximum drift 2%)")
    rate, offset = np.polyfit(x[best], y[best], 1)
    if np.ptp(x[best]) < 3 or np.max(np.abs(y[best] - (rate * x[best] + offset))) > .025:
        raise SyncError("Insufficient span or unstable drift fit")
    return Alignment(float(offset), float(rate), float(np.clip(points[best, 2].mean(), 0, 1)))


def sync(videos) -> list[Alignment]:
    """Return Alignment records in input order, relative to the first recording.

    Positive offset means the recording starts later in the match. Negative
    match times are valid. Raises SyncError instead of assuming zero offset.
    """
    videos = normalize(videos)
    reference = _features(videos[0].path)
    return [Alignment(0)] + [_align(reference, _features(v.path)) for v in videos[1:]]
