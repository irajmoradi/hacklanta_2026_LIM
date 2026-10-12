---
id: EXT-08
branch: ext/EXT-08
allowed_paths: [full_app/eval/**, Dockerfile, docker-compose.yml, .dockerignore, .github/**, docs/eval.md]
---
# EXT-08: Eval harness, Docker, CI
- **Eval harness** `full_app/eval/`: a labelled-set format (video path + ground-truth highlight intervals), metrics (precision/recall/F1 at IoU 0.3/0.5, mAP for ranking, time-to-first-clip, cost per minute of footage), and a runner comparing pipelines: Gemini-only vs signals-only vs signals + VLM window scoring (import the modules if present; skip gracefully if not). Include a synthetic labelled set generated with ffmpeg for CI.
- **Docker:** Dockerfile (python + ffmpeg + node build of the production frontend) and docker-compose; optional extras via build args (whisper, ocr, sam2).
- **CI:** GitHub Actions running pytest + frontend build on push to Extension (mock providers only, no secrets).
Tests: eval metrics unit tests. Write docs/eval.md. (The integrator writes the final README at the end; do not edit README.md.)
