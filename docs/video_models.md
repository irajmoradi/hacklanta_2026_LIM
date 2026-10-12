# Video understanding v2 (EXT-02)

The service API supports whole-video clip discovery and training-free scoring of
EXT-01 candidate windows. No training, downloaded media, model weights, OCR,
Torch, or Whisper dependencies are required. FFmpeg and FFprobe must be on PATH.

## Quick start

Run Python from `full_app/` after installing `requirements.txt`.

```python
from services.gemini_client import GeminiProvider
from services.video_understanding import ProviderConfig

# AI Studio: GEMINI_API_KEY in the process environment.
# Vertex express: GOOGLE_API_KEY and GOOGLE_GENAI_USE_VERTEXAI=true instead.
# No dotenv file is loaded implicitly by the provider.
with GeminiProvider(config=ProviderConfig(fps=4)) as provider:
    clips = provider.analyze_video("gameplay.mp4")  # validated ClipList
    candidates = [{
        "start": 10.0, "end": 18.0, "score": 1.7,
        "signals": {"motion": 2.0, "audio": 1.4}, "events": [],
    }]
    windows = provider.score_windows("gameplay.mp4", candidates)
    print([window.model_dump() for window in windows])
```

These commands make paid requests: discovery makes one inference per chunk and
scoring makes one per candidate, before retries. Use mocks during development;
the opt-in smoke test below makes only one inference attempt.

`VideoUnderstandingProvider` in `services/video_understanding.py` defines
`analyze_video(path, prompt) -> ClipList` and
`score_windows(path, candidates) -> list[ScoredWindow]`. Candidates can be JSON
dictionaries or Pydantic objects from EXT-01. There is no import dependency on
the signals implementation. Pass its candidates directly to `score_windows`.
For missing/empty candidate detection, call `analyze_video` explicitly as the
whole-video fallback; an empty scoring batch itself returns `[]` without calls.
Failures raise rather than silently triggering additional paid fallback requests.

Scored windows preserve `start/end/score/signals/events` and add:

| Field | Values |
| --- | --- |
| `player_alive` | `true`, `false`, or `null` when uncertain |
| `kind` | `highlight`, `lowlight`, `neutral` |
| `hype` | finite number from 0 to 10 |
| `caption` | one line, 1–240 characters |
| `reaction` | `sick_kill`, `clutch`, `bruh`, `fail`, `funny`, `wholesome`, `hype`, `roast` |

False/uncertain POV is normalized to neutral with hype 0. A player's own action
ending in death can still be a lowlight. Signals are hints, never proof of a kill.
All candidate bounds are checked before the first request. Scores stay in input
order; ranking/fusion remains the caller's responsibility.

## Gemini configuration and lifecycle

`GeminiProvider(api_key=None, model=None, config=None, vertexai=None,
media_resolution="low", agentic=False)` reads only the applicable environment
key. Explicit arguments take precedence. The model defaults to
`GEMINI_MODEL` or `gemini-3.5-flash-lite`.

| ProviderConfig field | Default | Meaning |
| --- | --- | --- |
| `chunk_seconds` | 600 | Maximum discovery chunk duration |
| `overlap_seconds` | 10 | Context shared by neighboring chunks; must be smaller than chunk |
| `fps` | 2 | Static Gemini sampling; 2–4 suggested for fast games |
| `timeout_seconds` | 120 | Each HTTP request and FFprobe invocation |
| `processing_timeout_seconds` | 300 | File processing polling budget / each FFmpeg invocation |
| `attempts` | 3 | Total application attempts, including the first |
| `backoff_seconds` | 1 | Exponential delays: 1, 2 seconds with defaults |
| `input_usd_per_million` | None | Optional caller-supplied input rate for estimates |
| `output_usd_per_million` | None | Optional caller-supplied output rate for estimates |

Long sources are re-encoded into overlapping MP4 chunks with audio retained and
local timelines reset. Prompts explicitly override full-source duration cues.
Validated local clip times are offset back into source seconds; timestamp aliases
must agree. A clip outside its chunk is rejected. Overlap duplicates are removed
when intersection covers at least half the shorter clip, keeping the earlier
observation. This conservative heuristic can merge nearby distinct moments;
reduce overlap if that matters. Temporary chunks/windows are removed even on
failure. Re-encoding adds CPU cost, and source-frame timing precision still applies.

AI Studio uses the File API. Upload reuse is scoped to the provider instance and
credential: SHA-256 of file contents, a one-hour TTL, and a 32-entry LRU by default.
Cache hits check the remote file state, and missing/failed/expired entries are
re-uploaded. `cache_ttl_seconds` and `cache_size` are constructor options.
This reuses uploads, not inference results or paid prompt-token caches. Repeated
analysis still incurs inference cost. Cache eviction and `close()` attempt remote
deletion; a context manager closes the client and clears uploads. Failed deletion
is logged without exposing error bodies or credentials. Long-lived Flask clients
retain reusable uploads until eviction or the service's own expiration.

Vertex express does not expose the Developer File API. Its adapter sends inline
MP4 bytes, guarded by `inline_limit_bytes` (20 MiB raw file bytes by default).
For larger media, reduce chunk duration or transcode first. A duration-based
chunk is not guaranteed to fit the byte limit, and base64/JSON add request
overhead: use a lower limit if your endpoint requires it. No GCS bucket or
service-account setup is silently assumed.

`agentic=True` uses the SDK's Interactions API on AI Studio with video
`processing="agentic"`, resolution, and a JSON response schema. Its request is
synchronous and bounded by the configured timeout. FPS is a static-mode control
and is not sent in agentic mode. If Interactions is unavailable, or Vertex express
is selected, the adapter warns once and uses standard `generate_content`
sampling. The standard path uses `response_schema` directly. Text-only edit
planning continues to use `generate_content`. The tested SDK is google-genai
2.29.0; the requirement excludes the next major version.

Transport timeouts/network errors, HTTP 408/429/500/502/503/504, malformed JSON,
and Pydantic response validation failures retry with bounded exponential backoff.
Authentication and other permanent errors fail immediately. Standard Gemini SDK
retries are set to one attempt to avoid multiplying application attempts.
Time limits apply per operation, not as a whole-video deadline; a final polling
request may finish after the processing deadline by up to one HTTP timeout.
INFO logs include provider/model, elapsed seconds, input/output token counts,
and estimated USD only if both rates were supplied (otherwise `None`). Thought
tokens are included when available. Estimates do not include cache discounts,
tool-specific fees, or provider-specific billing rules. No prices are hardcoded.

## Local open VLMs

```python
from services.local_vlm import OpenAICompatibleVLMProvider
from services.video_understanding import ProviderConfig

provider = OpenAICompatibleVLMProvider(
    model="your-served-qwen-vl-or-molmo-model",
    base_url="http://localhost:8000/v1",  # vLLM
    # base_url="http://localhost:11434/v1",  # Ollama
    config=ProviderConfig(fps=4, chunk_seconds=60, overlap_seconds=5),
    max_frames=32,
)
clips = provider.analyze_video("gameplay.mp4")
```

The adapter uses `/chat/completions`, ordered base64 JPEG image parts paired with
numeric timestamp text, and strict `response_format.json_schema`. An optional
`api_key` adds a Bearer header. No OpenAI SDK or cloud call is used. Select a
locally served vision model and server that support multiple images and JSON
schemas; model names are deployment-specific. Set the server's per-prompt image
limit to at least `max_frames`. Unsupported capabilities produce an explicit
server error rather than an unvalidated downgrade.

Frames are scaled to 640 pixels wide. The frame cap covers the entire input
uniformly, reducing effective FPS on long windows. Prefer short candidates for
fast gameplay: 32 frames cannot preserve every event in a ten-minute chunk.
This adapter supplies no audio. Schema validation cannot guarantee perceptual
accuracy; evaluate the chosen model on your games before relying on scores.

## Existing Flask integration

`GeminiVideoClient` retains the app's constructor and
`upload_video -> find_clips -> plan_edit -> generate_thumbnail` API.
`upload_video` now returns a deferred `VideoSource` handle; actual upload and
processing happen inside `find_clips`, avoiding an unnecessary full-file upload
before chunking. Existing app upload timing therefore measures staging only.
`find_clips` still returns list-of-dict clips and `plan_edit` a dict. A preexisting
SDK File is also accepted, but that caller owns its timeline/chunking.

`app.py` is outside EXT-02's allowed paths. It currently supplies its older model
default, so set `GEMINI_MODEL=gemini-3.5-flash-lite` to select the new default in
the UI. Its key gate still requires `GEMINI_API_KEY` or a request-provided key;
direct provider usage supports GOOGLE_API_KEY-only Vertex express. Wiring a
provider selector, GOOGLE-only Flask authentication, and candidate scoring into
routes belongs to integration work. No route/UI behavior was changed here.

## Tests and paid smoke test

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q"
```

Tests generate `testsrc2` and `sine` media with FFmpeg in pytest temporary
directories. All ordinary tests block network connections and mock model
responses. Coverage includes chunk offsets and duplicate removal, real slicing,
strict validation, retries/backoff, upload caching/expiry/deletion, Vertex and
AI Studio auth/config, agentic request/fallback, timestamped local frames, and
the legacy client through a real FFmpeg montage render.

`MockProvider([response_dict, ...], config=...)` supports scripted JSON strings,
dictionaries, and exceptions with the same validation/retry behavior. Its
`calls` list records path/prompt/schema for assertions. No credentials needed.

The single optional test is marked `live` and is skipped unless
`LIM_LIVE_SMOKE=1`. On a Linux runner that **already has credentials in its
runtime environment**, invoke:

```bash
tools/remote_run.sh "cd full_app && LIM_LIVE_SMOKE=1 GOOGLE_GENAI_USE_VERTEXAI=true python -m pytest -q -m live"
```

The test makes one `generate_content` attempt on synthetic footage, with both
SDK and application retries disabled. Do not run it more than three times per
task run. `LIM_LIVE_ENV_FILE` may point to an existing env file on the execution
machine; it is read only at runtime and never copied. The supplied Windows env
path is not present on the Linux runner. Do not put secrets into command lines,
test files, or the worktree to bridge that gap. No live calls were used to
validate this task; hosted model availability and live perception quality remain
unverified.

## Reference documentation

- [Google video input, sampling and agentic modes](https://ai.google.dev/gemini-api/docs/video-understanding)
- [Google Gen AI SDK, including File API scope](https://googleapis.github.io/python-genai/)
- [Interactions structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)
