"""Original deterministic oscillator/noise music; no recordings or soundfonts."""

import numpy as np

from .audio import SAMPLE_RATE, finish


def synthesize(style: str, length: float, bpm: float, beats, sections, seed: int):
    samples = np.zeros(round(length * SAMPLE_RATE), dtype=np.float32)
    rng = np.random.default_rng(seed)
    period = 60 / bpm
    energetic = style == "energetic"
    drop = sections[1].start

    def add(start, sound, gain=1):
        offset = round(start * SAMPLE_RATE)
        left, right = max(0, offset), min(len(samples), offset + len(sound))
        if right > left:
            samples[left:right] += gain * sound[left - offset:right - offset]

    # Extend by a beat for sustained notes crossing time zero.
    grid = [beats[0] - period] + beats
    for beat in grid:
        index = round((beat - drop) / period)
        t = np.arange(round(min(period, 0.32) * SAMPLE_RATE)) / SAMPLE_RATE
        kick = np.sin(2 * np.pi * (48 * t + 90 * .025 * (1 - np.exp(-t / .025))))
        add(beat, kick * np.exp(-t * 18), .48 if energetic else .32)
        if index % 2:
            add(beat, rng.normal(0, 1, len(t)) * np.exp(-t * 35), .09)
        for subdivision in range(2 if energetic else 1):
            ht = np.arange(round(.055 * SAMPLE_RATE)) / SAMPLE_RATE
            noise = rng.normal(0, 1, len(ht))
            add(beat + subdivision * period / 2, np.diff(noise, prepend=0)
                * np.exp(-ht * 90), .025)

        # A minor / F / C / G, a four-bar harmonic loop.
        root = [45, 41, 48, 43][(index // 4) % 4]
        nt = np.arange(round(period * .95 * SAMPLE_RATE)) / SAMPLE_RATE
        envelope = (1 - np.exp(-nt * 65)) * np.exp(-nt / (period * .45))
        frequency = 440 * 2 ** ((root - 69) / 12)
        bass = np.sin(2 * np.pi * frequency * nt)
        if energetic:
            bass += .25 * np.sin(2 * np.pi * frequency * 2 * nt)
        add(beat, bass * envelope, .20)
        # Sparse intro opens into a brighter arpeggio at the drop.
        if beat >= drop or index % 2 == 0:
            note = root + 12 + [0, 3 if root == 45 else 4, 7, 12][index % 4]
            frequency = 440 * 2 ** ((note - 69) / 12)
            lead = np.sin(2 * np.pi * frequency * nt)
            lead += .18 * np.sin(2 * np.pi * frequency * 3 * nt)
            add(beat, lead * envelope, .12 if energetic else .07)
    return finish(samples, sections)
