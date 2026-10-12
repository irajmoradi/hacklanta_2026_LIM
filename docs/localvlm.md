# Local gameplay VLM runtime (EXT-24)

`full_app/localvlm/` is an opt-in extension of EXT-02's
`OpenAICompatibleVLMProvider`. It implements `analyze_video` and `score_windows`
without Gemini, using JPEG images sent to a local OpenAI-compatible server.
Imports do not start processes or download models. Client dependencies are already
in the app requirements; ffmpeg and ffprobe must be on PATH. GPU libraries live in
the server, so the Flask app does not need torch, transformers, or vLLM installed.

## Start a server

From `full_app`, print a Linux/WSL shell command (review and execute it yourself):

```bash
python -m localvlm launch
```

The default Docker recipe uses `vllm/vllm-openai:v0.15.0`,
`Qwen/Qwen2.5-VL-7B-Instruct`, 16,384 context tokens, eight images per request,
one concurrent sequence, and 85% GPU memory utilization. It binds port 8000 to
loopback and caches weights in the `lim-vlm-models` Docker volume. Install Docker
and NVIDIA Container Toolkit first. Initial image/weight downloads need internet;
subsequent inference can run offline with cached weights. Pin a tested image digest
for your deployment; this task does not benchmark or certify the container on a GPU.

Other recipes:

```bash
python -m localvlm launch --model Qwen/Qwen3-VL-8B-Instruct
python -m localvlm launch --model allenai/Molmo2-8B
python -m localvlm launch --backend ollama
```

Qwen3-VL's comparable dense size is **8B**, not 7B. Molmo2 is also 8B and its
maintainers specify vLLM >=0.15.0. These are multi-image requests, not native video
inputs. Start all three with six full frames plus two HUD crops and 16K context;
lower frame count/resolution if your model's image expansion exhausts context.
Do not enable arbitrary remote model code just to work around a version mismatch.

The Ollama recipe prints `ollama serve`, `ollama pull qwen2.5vl:7b`, and
`ollama run qwen2.5vl:7b`. Run `serve` in a separate terminal (skip it if the desktop
service is already running). Before starting the server, set `OLLAMA_CONTEXT_LENGTH=16384`
in its environment; restart an existing service to apply it. `run` is an optional
interactive warm-up; exit its chat with `/bye`. Pulling weights needs internet.
Use the VL model: plain `qwen2.5:7b` cannot accept images. The client uses port
11434 and `/v1`, not Ollama's native `/api/chat` image format.

## Health and scoring

```bash
cd full_app
python -m localvlm health                  # vLLM, exit 0 if model listed; else 1
python -m localvlm health --backend ollama
python -m localvlm score --backend ollama --video /path/gameplay.mp4 --candidates /path/candidates.json
```

Candidate file contents (all times are absolute source seconds):

```json
[{"start": 1.0, "end": 5.0, "score": 0.8, "signals": {"motion": 0.9},
  "events": [{"time": 3.25, "type": "kill"}]}]
```

Health checks call `/v1/models` without generation and verify the exact model ID.
They establish server/model availability, not image support or inference quality.
`--url` and `--model` override the defaults. Set `LOCAL_VLM_API_KEY` only when your
server requires authentication; it is sent as a bearer header and never logged.
No Gemini key is needed. Do not expose an unauthenticated server outside loopback.

Python usage from `full_app`:

```python
from localvlm import LocalVLMProvider, RuntimeConfig, SamplerConfig, HUDRegion
from services.video_understanding import ProviderConfig

runtime = RuntimeConfig(backend="ollama", model="qwen2.5vl:7b",
                        base_url="http://127.0.0.1:11434/v1")
provider = LocalVLMProvider(runtime,
    config=ProviderConfig(timeout_seconds=120, attempts=2, backoff_seconds=1))
windows = provider.score_windows("gameplay.mp4", candidates, peaks=[3.25])
# provider.analyze_video("gameplay.mp4") also retains EXT-02's chunked ClipList API.
```

`peaks` is optional, one absolute timestamp (or None) per candidate. Without it,
the sampler chooses the valid event nearest the candidate midpoint, or the
midpoint when events are absent. This is a deterministic heuristic, not a learned
peak detector. All candidates and peaks are validated before inference starts.
Each window is re-encoded with timestamps reset; the sampler requests peak ±0.5s,
the peak, then beginning/end/interior context up to six distinct times. Sampling
uses accurate ffmpeg seek, not codec I-frames. An EOF guard can move a near-end
sample slightly earlier, and adjacent requests may decode the same source frame
in low-FPS inputs. Prefer short candidate windows (roughly 3–12 seconds) over
using six images to represent a long recording.

Two extra images crop the peak frame: upper-right kill feed and lower-left player
status. They are labeled as repeated views of that timestamp. Configure
`SamplerConfig(hud_regions=(HUDRegion(name="status", x=0, y=.8, width=.4, height=.2),))`
for your game's normalized coordinates, or `hud_regions=()` to disable crops.
The default positions are assumptions, not game detection. Frames/crops are scaled
to width 640 preserving aspect ratio and remain in memory; window slices use
temporary files cleaned after success or failure. Set `RuntimeConfig.image_budget`
to at least `sampler.image_budget` and launch the server with the same limit.

## Structured output and failure behavior

Two few-shot examples teach confirmed action vs spectator footage. The schema,
no-audio limitation, local timestamps, and conservative POV rules are included in
the prompt. Default `decoding="schema"` sends OpenAI `response_format.json_schema`,
supported by vLLM and Ollama. Alternatives: `"vllm"` sends the native
`structured_outputs.json` field; `"json"` requests JSON object mode; `"prompt"`
omits decoding constraints for servers without that capability. CLI equivalents
are `--decoding schema|vllm|json|prompt`. Select capabilities explicitly: a 400
response is surfaced, not silently retried using weaker constraints.

Responses may have markdown/prose wrappers or trailing commas repaired locally.
Repair never evaluates code, invents missing fields, coerces strings into booleans,
or clamps scores. Captions preserve punctuation. Multiple JSON objects, invalid
schemas and truncated outputs are rejected. Schema/JSON errors, timeouts and
transient HTTP errors use the inherited bounded retry policy (default three
attempts); 400-class configuration failures other than 408/429 fail immediately.
Each request has a timeout, and each ffmpeg operation has a processing timeout;
these are per-operation limits, not an overall batch deadline. Input images are
sampled once and reused across retries. Unknown/dead POV forces neutral/zero hype
after validation, matching EXT-02. Invalid inference never falls back to a paid API.

## Hardware and expected tradeoffs

These are planning estimates, **not measured benchmark results**:

| Runtime | Starting hardware budget | Expected use |
| --- | --- | --- |
| vLLM 7B/8B BF16 | NVIDIA GPU around 24 GB VRAM, 32 GB host RAM | Single-window requests; 16K context may still need tuning |
| Ollama 7B quantized | Around 12–16 GB GPU/unified memory, 16–32 GB host RAM | Smaller workstation; reduce context/images if memory constrained |
| CPU/offloaded Ollama | 32 GB host RAM recommended | Functional experimentation; expect much higher latency |

Raw BF16 weights alone take roughly 14–16 GB at these parameter counts, before
vision encoder overhead, caches, activations and runtime allocations. Allow tens
of GB of disk for container and weights. Server reports and an actual eight-image
request are the authority on fit; quantization, image preprocessing and context
length change the requirements substantially.

Expect seconds to tens of seconds per short window on a suitable GPU, potentially
minutes with CPU/offload; these are rough expectations with no throughput guarantee.
Compare cold-start separately from warm p50/p95 latency and record hardware,
quantization, image budget, context and server version. Use labeled gameplay
windows to measure kill/death precision, spectator false positives and invalid-JSON
rate. Against Gemini, expect weaker temporal reasoning and tiny-HUD reading from
small local models, especially at six frames/window. This path has no audio, so it
cannot judge speech or laughter directly. Upside: cached offline inference, local
data handling and no per-request API bill. No GPU inference or Gemini comparison
was performed for this task.

## Integration boundary and verification

The existing app provider factory and `pipeline/providers.py` are outside EXT-24's
allowed paths and remain unchanged. Instantiate `localvlm.LocalVLMProvider` via
Python or the CLI to use these improvements. Setting the app's existing local
provider option alone still uses the older adapter; its edit planner can still
call Gemini. End-to-end offline planning/render wiring belongs to the integrator;
this module provides working local analysis/scoring, not a replacement edit planner.

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_localvlm.py tests/test_video_understanding.py"
```

Tests generate synthetic ffmpeg video and use an ephemeral loopback mock server.
They exercise real HTTP request shape, crops, source/local offsets, response repair,
validation, bounded retries, timeouts, and health checks. All other test networking
remains blocked. No weights or paid API calls are required.

EXT-24 validation on the Linux runner:

- `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_localvlm.py tests/test_video_understanding.py"`:
  initial run exit 1, 60 passed / 1 failed. The HTTP timeout also limited ffprobe;
  fixed the new provider to use the processing timeout for media probing.
- `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_localvlm.py tests/test_video_understanding.py tests/test_pipeline.py"`:
  exit 0, 83 passed.
- `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_localvlm.py"`:
  final run after scoping scoring-specific prompt text to WindowAssessment,
  exit 0, 24 passed.
- No live model inference, model downloads, or Gemini calls were performed.

## Upstream references

- [vLLM multimodal inputs](https://docs.vllm.ai/en/stable/features/multimodal_inputs/)
- [vLLM structured outputs](https://github.com/vllm-project/vllm/blob/main/docs/features/structured_outputs.md)
- [Ollama OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx)
- [Ollama structured outputs](https://ollama.com/blog/structured-outputs)
- [Qwen3-VL 8B model](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
- [Molmo2 deployment/version guidance](https://github.com/allenai/molmo2/blob/main/README.md)
- [Ollama Qwen2.5-VL library](https://ollama.com/library/qwen2.5vl)
