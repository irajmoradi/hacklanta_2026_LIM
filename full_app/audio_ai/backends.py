"""Lazy optional backends: importing audio_ai never imports ML frameworks."""

import csv
import re
from pathlib import Path

import numpy as np

from .models import AudioEvent, Word

SAMPLE_RATE = 16000
CLASS_GROUPS = {
    "laugh": {"Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"},
    "shout": {"Shout", "Yell", "Screaming", "Battle cry"},
    "cheer": {"Cheering", "Whoop", "Crowd"},
    "gunfire": {"Gunshot, gunfire", "Machine gun", "Fusillade"},
}


def transcribe(samples: np.ndarray, model: str = "tiny", allow_downloads: bool = False) -> list[Word]:
    from faster_whisper import WhisperModel

    engine = WhisperModel(model, device="cpu", compute_type="int8",
                          local_files_only=not allow_downloads)
    segments, _ = engine.transcribe(samples, word_timestamps=True, vad_filter=True)
    return [Word(start=w.start, end=w.end, text=w.word.strip(),
                 probability=w.probability)
            for segment in segments for w in (segment.words or [])]


def speech_activity(samples: np.ndarray) -> np.ndarray:
    """WebRTC decisions on 20 ms, mono PCM16 frames (including final padding)."""
    import webrtcvad

    vad = webrtcvad.Vad(2)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    return np.array([
        float(vad.is_speech(np.pad(pcm[i:i + 320],
                                  (0, max(0, i + 320 - len(pcm)))).tobytes(), SAMPLE_RATE))
        for i in range(0, len(pcm), 320)
    ])


def classify(samples: np.ndarray, model_path: str | Path) -> list[tuple[float, float, dict[str, float]]]:
    """YAMNet local SavedModel; 0.96 s receptive fields with 0.48 s hop."""
    import tensorflow_hub as hub

    # A local path keeps model downloads an explicit provisioning step.
    path = Path(model_path)
    if not path.is_dir():
        raise ValueError("yamnet_model must be a local SavedModel directory")
    model = hub.load(str(path))
    with open(model.class_map_path().numpy().decode(), encoding="utf-8", newline="") as f:
        labels = [row["display_name"] for row in csv.DictReader(f)]
    indices = {kind: [i for i, label in enumerate(labels) if label in names]
               for kind, names in CLASS_GROUPS.items()}
    result = []
    # Bound inference memory; 24 s is exactly 50 model hops. Include overlap.
    for offset in range(0, len(samples), 24 * SAMPLE_RATE):
        chunk = samples[offset:offset + 24 * SAMPLE_RATE + 7680]
        scores, _, _ = model(np.pad(chunk, (0, max(0, 15600 - len(chunk)))))
        for i, row in enumerate(scores.numpy()[:50]):
            start = offset / SAMPLE_RATE + i * .48
            end = min(len(samples) / SAMPLE_RATE, start + .96)
            if start >= end:
                continue
            result.append((start, end, {
                kind: float(np.max(row[ids])) if ids else 0.0
                for kind, ids in indices.items()
            }))
    return result


def phrase_events(words: list[Word]) -> list[AudioEvent]:
    """Lexical excitement/surprise/frustration cues, not an emotion diagnosis."""
    phrases = {
        ("lets", "go"): "excitement", ("let", "us", "go"): "excitement",
        ("no", "way"): "surprise", ("bro",): "reaction",
        ("clutch",): "excitement", ("fuck",): "frustration_or_excitement",
        ("fucking",): "frustration_or_excitement", ("shit",): "frustration_or_excitement",
        ("damn",): "frustration_or_excitement",
    }
    tokens = []
    for word in words:
        normalized = word.text.lower().replace("'", "").replace("’", "")
        tokens.extend((token, word) for token in re.findall(r"[a-z]+", normalized))
    events = []
    for i in range(len(tokens)):
        for phrase, cue in phrases.items():
            match = tokens[i:i + len(phrase)]
            if tuple(t[0] for t in match) != phrase:
                continue
            if any(b[1].start - a[1].end > .8 for a, b in zip(match, match[1:])):
                continue
            score = min(t[1].probability for t in match)
            events.append(AudioEvent(start=match[0][1].start, end=match[-1][1].end,
                                     type="hype_phrase", score=score,
                                     signals={"audio_hype_phrase": score}, source="whisper",
                                     text=" ".join(phrase), cue=cue))
    return events
