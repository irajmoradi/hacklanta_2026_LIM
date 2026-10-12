"""Offline music beds: ``pick_or_generate(style, length, climax_at)``."""

from pathlib import Path
import tempfile
import uuid

import numpy as np

from .analysis import analyze_samples, analyze_track
from .audio import SAMPLE_RATE, finish, read_audio, write_audio
from .library import load_manifest, number, select_track
from .models import MusicBed, Section, TrackAnalysis, timeline
from .synthesis import synthesize

__all__ = ["MusicBed", "Section", "TrackAnalysis", "analyze_track", "load_manifest", "pick_or_generate"]


def pick_or_generate(style: str, length: float, climax_at: float, *, bpm=None,
                     manifest=None, mode=None, output_dir=None, seed: int = 0) -> MusicBed:
    """Create a mono 22.05 kHz PCM WAV and its timing/provenance metadata.

    Styles: energetic/chill. Length: (0, 600] seconds. Climax: [0, length).
    An explicit manifest is validated; no compatible track means synthesis.
    ``bpm`` targets synthesis only; library beds retain their native tempo.
    The caller owns the resulting file (including default temp-directory files).
    """
    if not isinstance(style, str) or style.lower() not in {"energetic", "chill"}:
        raise ValueError("style must be energetic or chill")
    style = style.lower()
    length = number(length, "length", 1 / SAMPLE_RATE, 600)
    climax_at = number(climax_at, "climax_at", 0, length)
    if climax_at >= length:
        raise ValueError("climax_at must be before the end of the bed")
    if mode is not None:
        if not isinstance(mode, str) or not mode.strip():
            raise ValueError("mode must be a nonempty string")
        mode = mode.strip().lower()
    target_bpm = number(bpm if bpm is not None else (140 if style == "energetic" else 85), "bpm", 40, 240)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    track = select_track(load_manifest(manifest), style, mode) if manifest is not None else None
    if track is not None:
        source = read_audio(track.path)
        tempo = track.bpm or analyze_samples(source).bpm
        if tempo is None:
            raise ValueError("Cannot estimate library tempo; provide bpm in the manifest")
        if track.drop_at >= len(source) / SAMPLE_RATE:
            raise ValueError("drop_at must be within the decoded music track")
        beats, sections = timeline(length, climax_at, tempo)
        # Repeat an integer number of beats to preserve tempo across seams.
        beat_count = int(len(source) / SAMPLE_RATE * tempo / 60 + 1e-9)
        if beat_count < 1:
            raise ValueError("Library track must contain at least one beat")
        loop_size = min(len(source), round(beat_count * 60 / tempo * SAMPLE_RATE))
        if round(track.drop_at * SAMPLE_RATE) >= loop_size:
            raise ValueError("drop_at must be within the whole-beat loop region")
        offset = round((track.drop_at - climax_at) * SAMPLE_RATE)
        indices = (np.arange(round(length * SAMPLE_RATE)) + offset) % loop_size
        samples = source[indices].copy()
        # De-click wrap seams without moving beats or the annotated drop.
        seams = np.flatnonzero(np.diff(indices) < 0) + 1
        fade = min(round(.005 * SAMPLE_RATE), loop_size // 4)
        for seam in seams:
            left, right = min(fade, seam), min(fade, len(samples) - seam)
            samples[seam - left:seam] *= np.linspace(1, .1, left)
            samples[seam:seam + right] *= np.linspace(.1, 1, right)
        samples = finish(samples, sections)
    else:
        tempo = target_bpm
        beats, sections = timeline(length, climax_at, tempo)
        samples = synthesize(style, length, tempo, beats, sections, seed)
    directory = Path(output_dir) if output_dir is not None else Path(tempfile.gettempdir()) / "lim-music"
    path = directory / f"music-{uuid.uuid4().hex}.wav"
    write_audio(path, samples)
    return MusicBed(path, tempo, beats, sections,
                    source=str(track.path) if track else "procedural",
                    license=track.license if track else None,
                    attribution=track.attribution if track else None)
