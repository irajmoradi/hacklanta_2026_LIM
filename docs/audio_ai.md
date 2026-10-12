# Audio analysis

`audio_ai.analyze(video_path) -> AudioSignals` extracts audio evidence without
changing the existing upload/analyze/plan/render flow. It accepts audio files too.
Run from `full_app/` after installing `requirements.txt`; `ffmpeg` and `ffprobe`
must be on PATH. NumPy is the only new core dependency. No Gemini calls or keys
are used, and the default never downloads model weights.

```python
from audio_ai import analyze

result = analyze("gameplay.mp4")
print(result.model_dump_json(indent=2))

# Reproducible heuristic-only execution, independent of installed ML extras:
result = analyze("gameplay.mp4", speech="off", vad="energy")

# Second audio stream, e.g. a separately recorded microphone:
mic = analyze("gameplay.mkv", audio_track=1)
```

```bash
cd full_app
python -m audio_ai gameplay.mp4 --speech off --vad energy
```

## Contract and fusion

`AudioSignals` is a Pydantic model with `duration`, `sample_rate` (16000),
`seconds`, `events`, `words`, `backends`, and `warnings`. `model_dump()` produces
plain dictionaries and `model_dump_json()` serializes them. There is one row per
second, with the last row clipped to media duration. Intervals are half-open
`[start, end)` in seconds on the media timeline. Delayed audio streams are padded
at the beginning; audio that ends before the video is treated as silence afterward.
The first audio stream is selected by default; `audio_track` is a zero-based
**audio** index, not an absolute container stream index.

Each second uses the candidate envelope:

```json
{
  "start": 3.0,
  "end": 4.0,
  "score": 0.82,
  "signals": {"audio_shout": 0.82, "audio_speech_activity": 1.0},
  "events": []
}
```

The example abbreviates the columns and events. `score` is the maximum of laugh,
shout, cheer, gunfire, and lexical hype evidence; it is not a calibrated probability
or a replacement for signal fusion. Prefixes avoid collisions with existing audio
loudness signals. This module does not depend on the candidate Python classes.

For a fusion table on the same second grid, merge each row's `signals` into the
corresponding fusion row. For a longer candidate, aggregate overlapping rows
(e.g. duration-weighted means for activity/share, maxima for excitement) and
include overlapping events. Do not blindly sum these correlated audio columns.

| Signal | Meaning / units |
| --- | --- |
| `audio_rms` | Linear full-scale amplitude, 0–1 |
| `audio_loudness_dbfs` | RMS dBFS, floored at -120; not LUFS |
| `audio_spectral_flux` | Mean positive change in normalized magnitude spectra, 0–1 |
| `audio_onset_density` | Detected onset starts per second, not a probability |
| `audio_speech_activity` | Fraction of time flagged by WebRTC VAD or energy fallback |
| `audio_voice_share` | Energy-weighted 250–3400 Hz share, or separated voice energy share |
| `audio_game_share` | Complement of voice share when audio is active |
| `audio_laugh`, `audio_shout`, `audio_cheer` | Heuristic evidence or maximum overlapping YAMNet score, 0–1 |
| `audio_gunfire_density` | Normalized onset/broadband proxy or YAMNet gunfire score, 0–1; not a shot count |
| `audio_hype_phrase` | Maximum overlapping phrase confidence, 0–1 |
| `audio_silence` | Fraction of time at or below `silence_db` (default -45 dBFS) |

On digital silence both source shares are zero. `events` contains `laugh`,
`shout`, `cheer`, `gunfire`, `hype_phrase`, and `silence`. Each event has
`start`, `end`, `score`, `signals`, `source`, and optional `text`/`cue` fields.
Adjacent positive second bins are merged (threshold .5; silence .95). These event
boundaries have one-second resolution. Hype phrases retain word-level timestamps.
Each row includes every overlapping event, so deduplicate if collecting events
from multiple rows; the top-level event list is already unique by construction.

## Speech and VAD extras

Heavy dependencies are in nested opt-in requirements files so the Linux runner's
`full_app/requirements*.txt` glob does not install them automatically:

```bash
pip install -r audio_ai/extras/speech.txt
```

The [faster-whisper API](https://github.com/SYSTRAN/faster-whisper) supports CPU
int8 inference and word timestamps. This adapter uses `tiny`, CPU, int8, and
`word_timestamps=True`. `whisper_model="base"` or a local model directory is also
supported. Both `speech="auto"` (default) and `speech="whisper"` attempt cached
weights only and fall back to no transcript when unavailable. `speech="off"`
skips the attempt entirely. To explicitly provision/use a model download:

```bash
python -m audio_ai gameplay.mp4 --speech whisper --whisper-model tiny --allow-model-downloads
```

`words` contains text, start/end seconds and model probability. Case-insensitive
whole-token cues include “let's go”, “no way”, “bro”, “clutch”, “fuck”, “fucking”,
“shit”, and “damn”. A gap over .8 seconds breaks a multiword phrase. Cue tags
describe lexical excitement, surprise, reaction, or ambiguous frustration/excitement;
they do not establish a speaker's emotion. No transcript is fabricated when ASR
is absent, and phrase confidence is the weakest word probability.

`vad="auto"` or `"webrtc"` attempts WebRTC on 20 ms mono PCM16 frames. If it is
missing or fails, the fallback uses frame energy above `silence_db`.
`vad="energy"` forces that fallback. Energy activity also responds to game sounds;
it is not reliable speech recognition. Word timestamps and VAD activity are
independent evidence.

## Optional pretrained event classifier

```bash
pip install -r audio_ai/extras/events.txt
python -m audio_ai gameplay.mp4 --yamnet-model /absolute/path/to/local/yamnet
```

Provision a local YAMNet SavedModel separately, following TensorFlow's
[YAMNet tutorial](https://www.tensorflow.org/hub/tutorials/yamnet).
The API equivalent is `events="yamnet", yamnet_model="/path/to/yamnet"`.
The adapter requires a local directory and reads its class map; it never fetches
a model URL. It groups laughter, shouting, cheering/crowd, and gunfire labels.
The model's 0.96-second windows at 0.48-second hops are mapped to overlapping
seconds using maxima. Inference uses 24-second chunks with overlap; the output
is cropped to media duration. Model windows can spread evidence into adjacent
bins. A successful classifier replaces heuristic event columns. Import, model,
or inference failures keep the entire heuristic result and add a warning.

The default heuristic combines RMS, spectral flux, and onset rhythm on 20 ms
frames: 2–8 separated bursts/second suggest laughter; sustained loud voice-band
energy suggests shouting; sustained loud broadband energy suggests cheering;
dense broadband onsets suggest gunfire. These are deliberately cheap proxies.
Music, repeated effects, and clipping can trigger them. A pure loud sine can
trigger `shout`; this is tested and is not a claim of semantic recognition.

## Source separation hook

The default voice/game split is only a band-energy hint. It cannot isolate chat
from game dialogue, identify a person, or distinguish vocals from music.
For deployments that already run Demucs/htdemucs, pass a callable:

```python
def separated_stems(samples, sample_rate):
    # Run your locally provisioned separator; resample/align its two stems.
    # Return mono float arrays of exactly len(samples), at sample_rate (16000).
    return voice_samples, game_samples

result = analyze("gameplay.mp4", separator=separated_stems)
```

This is an integration contract, not a built-in Demucs installation. The callable
receives a copy of decoded samples. Aligned stem energies replace the band share;
invalid shapes, nonfinite samples, or exceptions retain the band heuristic.
Game share represents the second stem only when the hook supplies it correctly.
The hook owns any optional ML dependencies and model provisioning.

## Operational behavior and validation

Missing optional components are recorded in `warnings`, and `backends` reports
what actually ran. Invalid configuration, nonexistent input, malformed media,
missing ffmpeg/ffprobe, invalid audio-track selection, and decode failures raise
errors instead of pretending the input is silent. Video without an audio stream
produces silence rows and a warning. Temporary decoded PCM is cleaned up.
Audio is loaded as mono float32 (about 38 MB for ten minutes); FFT work is batched.
Whisper and YAMNet may need substantially more memory and are not latency-guaranteed.

```bash
# From worktree root; all model APIs are mocked, no network/model/API calls:
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_audio_ai.py"
```

Tests generate seeded sine/noise bursts and ffmpeg `testsrc2` video, check event
timing and Candidate serialization, and exercise silent/short/invalid media,
delayed multitrack audio, CLI JSON, lexical cues, lazy model adapters, and fallback
behavior. An espeak-ng/espeak test synthesizes speech locally if available,
otherwise skips. It checks activity timing, not real ASR accuracy. Model accuracy
on gameplay and actual pretrained inference remain deployment validation work;
no model weights, media fixtures, or credentials belong in git.

### Sprint validation

Linux runner results for this task:

- `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_audio_ai.py"`
  — exit 0; initial milestone: 19 passed, 1 skipped.
- `tools/remote_run.sh "cd full_app && python -m pytest -q"`
  — exit 0; final suite: 23 passed, 1 skipped. The skip is local speech synthesis
  because neither espeak-ng nor espeak is installed on the runner.

Additional regression checks cover partial model-inference failure, invalid
classifier scores, VAD override behavior, and imports without heavy frameworks.
There were zero paid API calls and no pretrained model downloads. Real Whisper,
WebRTC, and YAMNet quality/installation were not validated by these mocked tests.
