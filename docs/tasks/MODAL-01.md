---
id: MODAL-01
branch: ext/MODAL-01
allowed_paths: [gpu/**, docs/gpu.md]
---
# MODAL-01: Optional GPU backend on Modal (SAM 3, Whisper large, V-JEPA features)
Create a separate, optional Modal app for this project in `gpu/` (do NOT deploy; the owner deploys): endpoints for **SAM 3** text-prompted video
segmentation (masks/tracks for the `sam/` remote backend), **faster-whisper large-v3** transcription with word timestamps (for `audio_ai/` + captions),
and **V-JEPA 2** window embeddings (for `vjepa/`). Scale-to-zero (`min_containers=0`), short scaledown window, max containers 1-2, a shared token
secret, request size limits, and clear cost estimates per minute of footage. Matching client adapters belong to the existing modules' remote-backend
interfaces: document the exact env vars/URLs to set. Include local unit tests for request/response schemas with mocked Modal. Write docs/gpu.md
with deploy commands and costs.
