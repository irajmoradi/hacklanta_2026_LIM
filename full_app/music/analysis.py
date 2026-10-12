"""Tempo/energy estimates with lazy, optional librosa and a NumPy fallback."""

import numpy as np

from .audio import SAMPLE_RATE, read_audio
from .models import TrackAnalysis


def analyze_samples(samples: np.ndarray, *, use_librosa: bool = True) -> TrackAnalysis:
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ValueError("Expected finite nonempty mono audio")
    energy = float(np.clip(np.sqrt(np.mean(samples ** 2)), 0, 1))
    duration = len(samples) / SAMPLE_RATE
    if duration < 2 or energy < 1e-5:
        return TrackAnalysis(None, energy, duration, "insufficient_signal")
    if use_librosa:
        try:
            import librosa

            tempo, _ = librosa.beat.beat_track(y=samples, sr=SAMPLE_RATE)
            bpm = float(np.asarray(tempo).reshape(-1)[0])
            if np.isfinite(bpm) and 40 <= bpm <= 240:
                return TrackAnalysis(bpm, energy, duration, "librosa")
        except Exception:
            # Missing or incompatible optional dependency must not break music.
            pass
    hop = 220  # ~100 Hz energy/onset envelope
    frames = samples[:len(samples) // hop * hop].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    onset = np.maximum(0, np.diff(rms, prepend=rms[0]))
    # Smooth frame quantization: off-grid beats otherwise correlate more strongly
    # at a two/three-beat multiple than at the true fractional-frame period.
    onset = np.convolve(onset, [.25, .5, .25], mode="same")
    onset -= onset.mean()
    if np.dot(onset, onset) < 1e-8:
        return TrackAnalysis(None, energy, duration, "autocorrelation")
    # FFT autocorrelation avoids quadratic work for long tracks.
    size = 1 << (2 * len(onset) - 1).bit_length()
    spectrum = np.fft.rfft(onset, n=size)
    corr = np.fft.irfft(spectrum * spectrum.conj(), n=size)[:len(onset)]
    corr /= np.arange(len(onset), 0, -1)
    rate = SAMPLE_RATE / hop
    low, high = int(rate * 60 / 240), min(int(np.ceil(rate * 60 / 40)), len(corr) - 2)
    peaks = [i for i in range(low, high + 1)
             if corr[i] > corr[i - 1] and corr[i] >= corr[i + 1] and corr[i] > .15 * corr[0]]
    if not peaks:
        return TrackAnalysis(None, energy, duration, "autocorrelation")
    best = max(corr[i] for i in peaks)
    # Prefer the shortest strong periodicity to avoid half-tempo multiples.
    lag = next(i for i in peaks if corr[i] >= .90 * best)
    a, b, c = corr[lag - 1:lag + 2]
    delta = .5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0
    bpm = float(np.clip(60 * rate / (lag + delta), 40, 240))
    return TrackAnalysis(bpm, energy, duration, "autocorrelation")


def analyze_track(path, *, use_librosa: bool = True) -> TrackAnalysis:
    """Analyze up to the first ten minutes; energy is amplitude RMS, not mood."""
    return analyze_samples(read_audio(path), use_librosa=use_librosa)
