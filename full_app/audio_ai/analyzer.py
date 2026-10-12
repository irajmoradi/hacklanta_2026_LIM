"""Decode once, measure 20 ms frames, and aggregate evidence on a second grid."""

import math
from pathlib import Path
import subprocess
import tempfile
from collections.abc import Iterable

import numpy as np

from vjepa.media import probe_media

from . import backends
from .models import AudioEvent, AudioSecond, AudioSignals, Word

RATE = backends.SAMPLE_RATE
FRAME = 320


def _decode(path: str | Path, track: int) -> tuple[np.ndarray, float, bool]:
    path = Path(path).resolve(strict=True)
    info = probe_media(path, timeout=60)
    streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    duration = float(info.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Media duration must be finite and nonnegative")
    if not streams and track == 0:
        return np.zeros(0, dtype=np.float32), duration, False
    if track >= len(streams):
        raise ValueError(f"Audio track {track} does not exist ({len(streams)} audio tracks)")
    with tempfile.TemporaryDirectory(prefix="audio-ai-") as directory:
        raw = Path(directory) / "mono.f32"
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-copyts", "-start_at_zero",
            "-i", str(path), "-map", f"0:a:{track}", "-vn", "-ac", "1",
            "-af", "aresample=16000:async=1:first_pts=0", "-ar", str(RATE),
            "-f", "f32le", str(raw)
        ], capture_output=True, check=True, timeout=3600)
        samples = np.fromfile(raw, dtype="<f4")
    samples = np.clip(np.nan_to_num(samples, nan=0, posinf=1, neginf=-1), -1, 1)
    return samples, max(duration, len(samples) / RATE), True


def _features(samples: np.ndarray, duration: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute frame features in bounded FFT batches, including the short tail."""
    count = math.ceil(duration * 50)
    rms, voice, flux = (np.zeros(count) for _ in range(3))
    weights = np.minimum(.02, np.maximum(0, duration - np.arange(count) / 50))
    freqs = np.fft.rfftfreq(FRAME, 1 / RATE)
    band = (freqs >= 250) & (freqs <= 3400)
    window = np.hanning(FRAME)
    previous = np.zeros(FRAME // 2 + 1)
    for base in range(0, count, 500):
        n = min(500, count - base)
        chunk = samples[base * FRAME:(base + n) * FRAME]
        frames = np.pad(chunk, (0, n * FRAME - len(chunk))).reshape(n, FRAME)
        lengths = np.clip(duration * RATE - np.arange(base, base + n) * FRAME, 1, FRAME)
        rms[base:base + n] = np.sqrt(np.sum(frames ** 2, axis=1) / lengths)
        spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
        power = spectrum ** 2
        voice[base:base + n] = power[:, band].sum(axis=1) / (power.sum(axis=1) + 1e-12)
        normalized = spectrum / (spectrum.sum(axis=1, keepdims=True) + 1e-12)
        difference = normalized - np.vstack([previous, normalized[:-1]])
        flux[base:base + n] = np.maximum(difference, 0).sum(axis=1)
        previous = normalized[-1]
    return rms, voice, flux, weights


def _interval_events(rows: list[AudioSecond], key: str, kind: str,
                     source: str, threshold: float = .5) -> list[AudioEvent]:
    result = []
    for row in rows:
        score = row.signals[key]
        if score < threshold:
            continue
        if result and result[-1].end == row.start:
            event = result[-1]
            event.end = row.end
            event.score = max(event.score, score)
            event.signals[key] = event.score
        else:
            result.append(AudioEvent(start=row.start, end=row.end, type=kind,
                                     score=score, signals={key: score}, source=source))
    return result


def _transcript(words: Iterable[Word | dict], duration: float) -> list[Word]:
    result = []
    for value in words:
        word = Word.model_validate(value)
        if not all(math.isfinite(v) for v in (word.start, word.end, word.probability)):
            continue
        word.start, word.end = max(0, word.start), min(duration, word.end)
        word.probability = float(np.clip(word.probability, 0, 1))
        if word.start < word.end:
            result.append(word)
    return sorted(result, key=lambda word: (word.start, word.end))


def _classifications(predictions: Iterable[tuple[float, float, dict[str, float]]],
                     count: int) -> list[dict[str, float]]:
    classified = [{kind: 0.0 for kind in backends.CLASS_GROUPS} for _ in range(count)]
    for start, end, scores in predictions:
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError("Invalid classifier interval")
        for i in range(max(0, int(start)), min(count, math.ceil(end))):
            for kind, score in scores.items():
                if kind not in classified[i] or not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("Invalid classifier score")
                classified[i][kind] = max(classified[i][kind], score)
    return classified


def analyze(video_path, *, audio_track=0, speech="auto", whisper_model="tiny",
            allow_model_downloads=False, vad="auto", events="heuristic",
            yamnet_model=None, separator=None, silence_db=-45.0) -> AudioSignals:
    """Analyze a mixed or mic track. See docs/audio_ai.md for units and caveats.

    Optional separator(samples.copy(), 16000) -> (voice, game) must return
    aligned mono arrays; a Demucs adapter can resample its stems to this grid.
    Missing/broken optional dependencies produce warnings and retain heuristics.
    Invalid inputs and ffmpeg failures deliberately propagate to the caller.
    """
    if isinstance(audio_track, bool) or not isinstance(audio_track, int) or audio_track < 0:
        raise ValueError("audio_track must be a nonnegative audio stream index")
    if speech not in {"auto", "off", "whisper"} or vad not in {"auto", "energy", "webrtc"}:
        raise ValueError("Invalid speech or vad backend")
    if events not in {"heuristic", "yamnet"}:
        raise ValueError("Invalid events backend")
    if not math.isfinite(silence_db) or not -120 <= silence_db <= 0:
        raise ValueError("silence_db must be between -120 and 0 dBFS")
    samples, duration, has_audio = _decode(video_path, audio_track)
    result = AudioSignals(duration=duration, backends={
        "speech": "off", "vad": "energy", "events": "heuristic", "separation": "band_energy"
    })
    if not has_audio:
        result.warnings.append("No audio stream; emitting silence over the media duration.")
    if duration == 0:
        return result
    rms, voice, flux, weights = _features(samples, duration)
    frame_power = rms ** 2
    active = rms > 10 ** (silence_db / 20)
    speech_frames = active.astype(float)

    def fallback(name, exc):
        result.warnings.append(f"{name} unavailable ({type(exc).__name__}); using fallback.")

    if has_audio and len(samples) and vad != "energy":
        try:
            decisions = backends.speech_activity(samples)
            speech_frames[:len(decisions)] = decisions
            result.backends["vad"] = "webrtc"
        except Exception as exc:
            fallback("WebRTC VAD", exc)
    if has_audio and len(samples) and speech != "off":
        try:
            words = backends.transcribe(samples, whisper_model, allow_model_downloads)
            result.words = _transcript(words, duration)
            result.backends["speech"] = "faster-whisper"
        except Exception as exc:
            fallback("Whisper", exc)
    if has_audio and len(samples) and separator is not None:
        try:
            stems = [np.asarray(x, dtype=np.float32) for x in separator(samples.copy(), RATE)]
            if len(stems) != 2 or any(x.shape != samples.shape or not np.isfinite(x).all() for x in stems):
                raise ValueError("Separator must return two finite aligned mono stems")
            energy = [_features(x, duration)[0] ** 2 for x in stems]
            voice = energy[0] / (energy[0] + energy[1] + 1e-12)
            result.backends["separation"] = "separator_hook"
        except Exception as exc:
            fallback("Source separator", exc)

    # Onset starts, with a minimum 60 ms refractory period. Rhythm is evidence,
    # never a claim that a laugh or gunshot has been semantically recognized.
    onset = np.zeros(len(rms), dtype=bool)
    previous_rms = np.r_[0, rms[:-1]]
    rising = active & ((rms > previous_rms * 1.8 + .008) |
                       ((flux > .55) & (rms > previous_rms + .008)))
    last = -3
    for index in np.flatnonzero(rising):
        if index - last >= 3:
            onset[index] = True
            last = index
    for second in range(math.ceil(duration)):
        start, end = float(second), min(float(second + 1), duration)
        sl = slice(second * 50, min((second + 1) * 50, len(rms)))
        w = weights[sl]

        def mean(values):
            return float(np.average(values[sl], weights=w))

        activity = mean(active)
        loudness = math.sqrt(mean(frame_power))
        share = float(np.sum(voice[sl] * rms[sl] ** 2 * w) /
                      (np.sum(rms[sl] ** 2 * w) + 1e-12)) if activity else 0.0
        bursts = float(onset[sl].sum()) / (end - start)
        laugh = min(1.0, bursts / 4) * min(1.0, loudness / .07) if 2 <= bursts <= 8 and .12 <= activity <= .85 else 0.0
        shout = min(1.0, loudness / .2) * share if activity >= .65 else 0.0
        cheer = min(1.0, loudness / .2) * (1 - share) if activity >= .65 else 0.0
        gunfire = min(1.0, bursts / 8) * (1 - share) if bursts >= 3 else 0.0
        signals = {
            "audio_rms": loudness, "audio_loudness_dbfs": max(-120.0, 20 * math.log10(max(loudness, 1e-6))),
            "audio_spectral_flux": mean(flux), "audio_onset_density": bursts,
            "audio_speech_activity": mean(speech_frames), "audio_voice_share": share,
            "audio_game_share": 1 - share if activity else 0.0,
            "audio_laugh": laugh, "audio_shout": shout, "audio_cheer": cheer,
            "audio_gunfire_density": gunfire, "audio_hype_phrase": 0.0,
            "audio_silence": 1 - activity,
        }
        result.seconds.append(AudioSecond(start=start, end=end, score=0.0, signals=signals))

    if has_audio and len(samples) and events == "yamnet":
        try:
            predictions = backends.classify(samples, yamnet_model)
            # Replace only after the entire optional backend succeeds.
            classified = _classifications(predictions, len(result.seconds))
            for row, scores in zip(result.seconds, classified):
                for kind, score in scores.items():
                    key = "audio_gunfire_density" if kind == "gunfire" else f"audio_{kind}"
                    row.signals[key] = score
            result.backends["events"] = "yamnet"
        except Exception as exc:
            fallback("YAMNet", exc)
    result.events = backends.phrase_events(result.words)
    for kind in ("laugh", "shout", "cheer", "gunfire", "silence"):
        key = "audio_gunfire_density" if kind == "gunfire" else f"audio_{kind}"
        result.events.extend(_interval_events(result.seconds, key, kind,
                             "energy" if kind == "silence" else result.backends["events"],
                             .95 if kind == "silence" else .5))
    result.events.sort(key=lambda event: (event.start, event.end, event.type))
    for row in result.seconds:
        row.events = [event for event in result.events if event.start < row.end and event.end > row.start]
        row.signals["audio_hype_phrase"] = max(
            (event.score for event in row.events if event.type == "hype_phrase"), default=0.0)
        row.score = max(row.signals[key] for key in (
            "audio_laugh", "audio_shout", "audio_cheer", "audio_gunfire_density", "audio_hype_phrase"))
    return result
