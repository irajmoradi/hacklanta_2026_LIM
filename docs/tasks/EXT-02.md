---
id: EXT-02
branch: ext/EXT-02
allowed_paths: [full_app/services/**, full_app/prompts/**, full_app/models/schemas.py, full_app/tests/**, full_app/requirements*.txt, docs/video_models.md]
---
# EXT-02: Video-understanding layer v2 (providers, chunking, window scoring)
Upgrade `services/gemini_client.py` into a provider layer (see docs/RESEARCH.md sections 2-4):
- `VideoUnderstandingProvider` interface; `GeminiProvider` (google-genai; supports AI Studio `GEMINI_API_KEY` **and** Vertex express via `GOOGLE_API_KEY` + `GOOGLE_GENAI_USE_VERTEXAI=true`), and an `OpenAICompatibleVLMProvider` for local open VLMs (Qwen-VL / Molmo via vLLM or Ollama: sends sampled frames + timestamps).
- Gemini config: model (default `gemini-3.5-flash-lite`), `media_resolution` (low by default), custom fps for fast games (2-4), File API upload with reuse/caching by file hash, **chunking** long videos (default 10 min chunks with overlap) and offsetting timestamps; optional agentic processing flag if the SDK supports it.
- **Window scoring (REZE-style, training-free):** given candidate windows (EXT-01 `Candidate` JSON: start/end/score/signals), score each window with the VLM using a short structured prompt (is the player alive? highlight vs lowlight? hype 0-10, a one-line caption, a suggested reaction label from {sick_kill, clutch, bruh, fail, funny, wholesome, hype, roast}) and return validated Pydantic objects. Keep the existing whole-video find-clips mode as a fallback.
- Strict JSON schemas (response_schema), retries with backoff, timeouts, cost/time logging, and a mock provider for tests.
Tests: mocked provider responses (no network) for chunk offsetting, schema validation, retry, cache. One optional `-m live` smoke test (at most 3 calls). Write docs/video_models.md.
