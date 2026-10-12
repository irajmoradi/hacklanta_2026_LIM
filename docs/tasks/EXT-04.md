---
id: EXT-04
branch: ext/EXT-04
allowed_paths: [full_app/services/ffmpeg_runner.py, full_app/render/**, full_app/models/effects.py, full_app/tests/**, full_app/requirements*.txt, docs/rendering.md]
---
# EXT-04: Render engine v2 (vertical exports, captions, beat sync, transitions)
Build `full_app/render/` (use and extend `services/ffmpeg_runner.py`):
- **Export presets:** landscape 16:9, **vertical 9:16 (Shorts/TikTok/Reels)**, square 1:1, at 1080p/720p, h264 + aac, NVENC when available else libx264.
- **Smart reframe for vertical:** track the action region per clip (motion saliency / frame-difference centroid smoothed over time; accept an optional external subject track from `sam.subject_track` when present) and pan a 9:16 crop smoothly; crosshair-centered default for FPS games; optional blurred-background letterbox mode.
- **Auto-captions:** optional faster-whisper word-level transcripts of in-clip voice, styled burned-in captions (ASS subtitles, per-word pop-in, safe areas per preset), profanity masking option.
- **Beat sync:** optional music bed; detect beats (librosa or ffmpeg energy) and snap cut points to beats; duck music under speech/SFX.
- **Transitions:** xfade presets (fast zoom, whip, flash, glitch) between clips; intro/outro cards; titles with the existing meme overlays.
- A declarative `RenderPlan` (Pydantic) the planner fills and the renderer executes; deterministic filtergraph builder with unit tests.
Tests: render short synthetic clips into each preset and assert duration/resolution/streams with ffprobe; filtergraph snapshot tests. Document in docs/rendering.md.
