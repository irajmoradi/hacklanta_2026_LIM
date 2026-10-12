# Video-understanding research notes (Extension sprint, Oct 2026)

What the current state of the art suggests for a gameplay clip editor:

1. **Multi-signal fusion beats a single prompt.** Commercial clippers (e.g. Eklipse "Gameplay Intelligence", 2026) score each
   candidate moment on several signals at once: game-state events (kills/deaths/round wins from the HUD), audio composition
   (player voice vs in-game audio vs music; shouting/laughter spikes), on-screen action density (motion), and continuity
   (does the moment form a complete beat). Open-source projects read the kill feed with OCR (montage_maker; RapidOCR) or a small
   detector (NiceShot: YOLOv8n for kill/death/medal events) and cut dead air.
2. **Training-free highlight scoring with VLMs.** REZE (2026) scores short windows with an off-the-shelf VLM and aggregates
   the scores to get highlight detection and temporal grounding with no training. Practical pattern: propose candidate windows
   cheaply (scene cuts, audio peaks, OCR events), then ask the VLM to score/describe each window, then fuse and rank.
3. **Gemini 3.x video specifics.** The File API is the right input for long videos. `media_resolution` (tokens per frame) and the
   processing mode are separate controls; newer Flash/Flash-Lite models support **agentic video understanding** (the model
   navigates the timeline and loads only needed frames/audio/transcript). Default sampling is 1 FPS; use a custom higher fps for
   fast motion (FPS games). Timestamps can drift on very long videos: chunk (~10–20 min) and offset, or re-encode to constant fps.
   Ask for structured JSON with timestamps and validate it.
4. **Open models for a local/offline path.** Qwen-family VL, InternVL, Molmo2 (open-weights video VLM with spatiotemporal
   grounding) are the common bases. Keep a provider interface so a local VLM (e.g. via vLLM/Ollama) can replace Gemini.
5. **Classic CV/audio building blocks** (cheap, deterministic): shot-boundary detection (PySceneDetect content/adaptive detectors,
   or TransNetV2), audio RMS/onset peaks (ffmpeg `astats`/`ebur128` or librosa), speech transcripts with word timestamps
   (faster-whisper / WhisperX) for captions and "funny moment" cues, OCR (RapidOCR/Tesseract) on HUD regions, optical-flow or
   frame-difference motion energy.

Sources: arxiv.org/pdf/2608.04480 (REZE), github.com/NVlabs/VideoITG, emergentmind.com/papers/2601.10611 (Molmo2),
ai.google.dev/gemini-api/docs/video-understanding, ai.google.dev/gemini-api/docs/media-resolution,
github.com/rlmsinclair/montage_maker, letsdatascience.com/news/niceshot-ai-detects-key-gameplay-events-b6e93d44,
blog.eklipse.gg/streaming-tips/gameplay-intelligence.html
