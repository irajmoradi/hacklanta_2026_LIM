---
id: EXT-24
branch: ext/EXT-24
allowed_paths: [full_app/localvlm/**, full_app/tests/**, docs/localvlm.md]
---
# EXT-24: Local open-VLM runtime (Qwen-VL / Molmo via vLLM or Ollama)
The provider layer (`services/`, EXT-02) has an `OpenAICompatibleVLMProvider`. Build `full_app/localvlm/` to make the offline path real:
launch/config helpers for **vLLM** (Docker command + recommended Qwen2.5/3-VL 7B or Molmo2 settings, max-model-len, frames per window) and **Ollama**
(model pull + run), a frame sampler tuned for gameplay windows (keyframes around the candidate peak, HUD crops included as extra images), prompt
adapters that make small VLMs answer the window-scoring JSON reliably (few-shot, JSON repair, constrained decoding when the server supports it), and a
health check. Tests with a mocked OpenAI-compatible server (request shape, JSON repair, timeouts). Write docs/localvlm.md with hardware needs and expected speed/quality vs Gemini.
