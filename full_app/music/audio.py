"""Small PCM/ffmpeg boundary; no optional Python audio dependencies required."""

from pathlib import Path
import subprocess
import wave

import numpy as np

SAMPLE_RATE = 22050


def read_audio(path: str | Path, *, max_seconds: float = 600) -> np.ndarray:
    """Decode mono float audio; bound analysis memory and support ffmpeg formats."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-t", str(max_seconds),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
            check=True, capture_output=True, timeout=120,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to read user music tracks") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Unable to decode music track: {path.name}") from exc
    samples = np.frombuffer(result.stdout, dtype="<f4").copy()
    if not samples.size or not np.isfinite(samples).all():
        raise ValueError("Music track contains no usable audio")
    return samples


def write_audio(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.tobytes())


def finish(samples: np.ndarray, sections) -> np.ndarray:
    """Section dynamics plus short edge fades; normalize only to prevent clipping."""
    samples = samples.copy()
    drop = round(sections[1].start * SAMPLE_RATE)
    outro = round(sections[2].start * SAMPLE_RATE)
    samples[:drop] *= np.linspace(0.30, 0.55, drop)
    samples[outro:] *= np.linspace(1, 0, len(samples) - outro)
    fade = min(round(0.01 * SAMPLE_RATE), len(samples) // 2)
    if fade:
        samples[:fade] *= np.linspace(0, 1, fade)
        samples[-fade:] *= np.linspace(1, 0, fade)
    peak = float(np.max(np.abs(samples)))
    if peak > 0.9:
        samples *= 0.9 / peak
    return samples
