---
id: EXT-11
branch: ext/EXT-11
allowed_paths: [full_app/audio_ai/**, full_app/tests/**, full_app/requirements*.txt, docs/audio_ai.md]
---
# EXT-11: Audio intelligence signals (voice chat, laughter, hype)
Gameplay highlights are often defined by the **audio**: teammates screaming, laughing, the player's commentary. Build `full_app/audio_ai/`:
- **Speech:** faster-whisper (optional extra; `tiny`/`base` on CPU by default) word-level transcript of the mixed or mic track; keyword/emotion cues
  ("let's go", "no way", "bro", "clutch", swears) with timestamps; per-second speech activity (VAD, e.g. silero-vad or webrtcvad, fallback energy-based).
- **Audio events:** laughter / shouting / cheering / gunfire-density detection with a small pretrained classifier (YAMNet / PANNs / CLAP zero-shot via
  an optional extra) and a heuristic fallback (spectral flux + loudness).
- **Source separation hint:** estimate voice vs game audio share per second (simple band-energy heuristic; optional demucs/htdemucs hook).
- Output a per-second `AudioSignals` table + event list (`laugh`, `shout`, `hype_phrase`, `silence`) in the same Candidate-signal shape EXT-01 uses
  (`signals{...}` dict keyed by name) so fusion can add these columns; `audio_ai.analyze(video_path) -> AudioSignals`.
Tests on synthetic audio (sine bursts, noise bursts shaped like laughter, TTS-free tone patterns; and a short espeak-ng/pyttsx3 or prerecorded
synthetic speech file generated in the test if available, else skip) asserting events land at the right times. Write docs/audio_ai.md.
