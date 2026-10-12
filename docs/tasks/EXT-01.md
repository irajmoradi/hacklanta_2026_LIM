---
id: EXT-01
branch: ext/EXT-01
allowed_paths: [full_app/signals/**, full_app/tests/**, full_app/requirements*.txt, docs/signals.md]
---
# EXT-01: Multi-signal candidate detection + fusion (cheap, deterministic, no paid APIs)
Build `full_app/signals/` that turns a gameplay video into **ranked candidate moments** before any LLM call (see docs/RESEARCH.md sections 1 and 5):
- **Shot/scene cuts** (PySceneDetect ContentDetector/AdaptiveDetector; fallback ffmpeg `select='gt(scene,0.3)'`).
- **Audio:** loudness/RMS and onset peaks (ffmpeg `ebur128`/`astats` or librosa), sustained-spike detection (gunfights, shouting, laughter-like bursts).
- **Motion/action density:** frame-difference energy on downscaled frames (OpenCV), per second.
- **HUD/kill-feed OCR (optional extra):** sample frames at 2-4 fps, crop configurable HUD regions per game profile (Valorant / Overwatch 2 / Deadlock defaults: kill feed top-right, ELIMINATED / KILLED BY banners), OCR with RapidOCR or Tesseract, detect kill/death events. Graceful fallback when OCR is not installed.
- **Fusion:** z-score each signal per second, combine with tunable weights into an interest curve; peak-pick candidate windows (pre-roll/post-roll, merge overlaps, min/max length), emit `Candidate{start,end,score,signals{...},events[]}` JSON. Dead-air detection (low motion + low audio) for trimming.
Public API: `detect_candidates(video_path, profile="auto", **cfg) -> list[Candidate]` plus a CLI `python -m signals <video>` printing JSON. Fast: a 10-minute 1080p video in under 60 s on 12 CPU cores (downscale + frame skip).
Tests: synthetic videos made with ffmpeg (testsrc2 with sudden motion bursts, sine tones with loud spikes, drawtext ELIMINATED BY banners) asserting the right windows are found. Document weights/profiles in docs/signals.md.
