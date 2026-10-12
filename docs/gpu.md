# Optional Modal GPU backend (MODAL-01)

This is a separate, opt-in app; no upload/analyze/plan/render defaults change.
Nothing was deployed, no weights were downloaded, and no live inference or Gemini
calls were made during implementation. The owner performs deployment and a real
GPU smoke test. All implementation and tests live in `gpu/` by task scope.

## Deployment by the owner

From the repository root in a separate Python 3.12 environment:

```bash
python -m pip install 'modal>=1.0,<2'
python -m modal setup
```

Request and accept access to [Meta's SAM 3 weights](https://huggingface.co/facebook/sam3)
and comply with its model license. In the Modal dashboard create **`lim-gpu-auth`**
with two keys: `GPU_API_TOKEN` (a newly generated high-entropy shared service token)
and `HF_TOKEN` (a Hugging Face token with access to those weights). These are not
Gemini credentials. Keep both in the secret manager, never source control or CLI
history. The service rejects requests if its token is absent.

Choose the full 40-character commit of
`facebook/vjepa2-vitl-fpc64-256` from its Hugging Face history. Use exactly that
revision for training, server, and client:

```bash
export VJEPA_REVISION='<40-character-Hugging-Face-commit>'
# This command creates the deployment and can incur charges; owner only:
python -m modal deploy -m gpu.modal_app
```

The CLI prints the URL of `api`. Copy that exact URL as `GPU_BASE_URL`; Modal
workspace/environment names determine the hostname. Append `/segment`, `/track`,
`/transcribe`, or `/embed`. There is no public health or documentation endpoint.
Stop the app with `python -m modal app stop lim-optional-gpu` when finished.

The image pins SAM source to `0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc`,
PyTorch 2.7.1/CUDA 12.6, faster-whisper 1.2.1, and Transformers 4.57.1.
Some transitive packages remain version ranges. The optional dependencies are
confined to the Modal image; ordinary app imports install/load none of them.
Initial authenticated inference downloads weights into the named
`lim-gpu-model-cache` volume. Only weights persist there; submitted media is held
in memory, with temporary SAM JPEG frames removed on success or failure.

One A100-80GB worker serves all four operations **serially**, loading one model
family at a time. Changing operations evicts the previous model, so group requests
by operation to avoid reload costs. It has `min_containers=0`, `max_containers=1`,
`buffer_containers=0`, a 30-second scaledown window, 240-second execution timeout,
and no retries. The CPU authentication gateway has the same container bounds and
a 300-second timeout. Total service maximum is one GPU plus one CPU container.
These are concurrency bounds, not a monthly spending cap: set a Modal workspace
budget and monitor usage. Rolling deployments can temporarily overlap containers.

## Wire contracts and limits

All requests are HTTPS POST, `Content-Type: application/json`, with
`Authorization: Bearer <GPU_API_TOKEN>`. Authentication and validation happen on
the CPU before GPU dispatch. There are no URL fetches, local path inputs, arbitrary
checkpoint arguments, pickle, or shell commands derived from requests.

The streamed JSON body limit is 18 MiB, including base64 overhead. Responses are
limited to 8 MiB. Unknown fields are rejected. Status codes: 401 missing/incorrect
token, 404 unknown operation, 415 wrong content type, 413 body too large, 422
invalid input, 503 inference failure or invalid/oversized model output. Error
bodies are generic and exclude model exception strings, credentials, and media.

| Path | Request | Successful response |
|---|---|---|
| `/segment` | `{"image_png":"<base64 PNG>","prompt":"player character"}` | `{"mask":[[0,1],...]}` at the exact input height/width |
| `/track` | `{"frames_png":["<base64 PNG>",...],"fps":4,"prompt":"enemy"}` | `{"width":256,"height":144,"frames":[{"frame_index":0,"time":0.0,"objects":[{"id":7,"rle":[5,3,...],"box":[0.1,0.2,0.4,0.8]}]}]}` |
| `/transcribe` | `{"pcm_f32le":"<base64 float32 PCM>","sample_rate":16000}` | `{"language":"en","words":[{"start":0.1,"end":0.4,"text":"go","probability":0.95}]}` |
| `/embed` | `{"rgb_u8":"<base64 RGB bytes>","frames":32,"encoder":"hf-mean-v1:facebook/vjepa2-vitl-fpc64-256@<commit>"}` | `{"encoder":"<same fingerprint>","features":[<1024 finite floats>]}` |

PNG inputs must be at most 256x256 and 256 KiB each. The SAM image result is the
union of matching instances, with 0 background and 1 foreground. No detection
returns an all-zero mask; the existing SAM client deliberately treats this as a
fallback condition. Text is a nonblank phrase of at most 160 characters.

Tracking accepts 2–48 equally sized frames, a positive FPS at most 60, and at most
12 seconds (`frame_count/fps`). Sample frames locally from owned footage, e.g.
4 FPS at a maximum 256-pixel long edge. SAM 3 propagates the first-frame text prompt
through the JPEG sequence. IDs persist within a request only. Times are relative
to the submitted sequence; callers add the source offset. Each object has a
normalized `[left,top,right,bottom]` bounding box with exclusive right/bottom and
a **row-major** RLE mask: alternating zero/one counts beginning with a zero count,
including an initial 0 for a foreground first pixel. Counts sum to width*height.
At most 32 objects per frame are returned; excessive detections/output fail the
request rather than silently dropping objects. Empty detections yield empty lists.
This sampled-frame contract avoids unbounded video decoding on the server.

Audio is mono, 16 kHz, normalized finite little-endian float32 in [-1,1], nonempty,
at most 60 seconds. No container/WAV header. Word times are relative to the chunk.
Whisper runs large-v3 with VAD and word timestamps, including full consumption of
its lazy segment generator. Silent input may return an empty word list.

Embeddings accept exactly one contiguous `[T,256,256,3]` uint8 RGB array, even
T from 16 to 64. Sample/resize/repeat-pad locally using `vjepa.features.decode`.
The server preserves this grid, normalizes using the HF processor, runs the frozen
vision encoder, and mean-pools tokens. There is no predictor or gameplay classifier
in this endpoint. Fingerprints must match the pinned server model; an incompatible
head must be retrained, not relabeled.

## Existing module adapters

Keep repository root and `full_app` on Python's module path:

```bash
export PYTHONPATH="$PWD:$PWD/full_app"
export GPU_BASE_URL='https://<exact-host-printed-by-modal>'
# Load GPU_API_TOKEN securely into this process; do not save it in a tracked file.
export SAM_BACKEND=remote
export SAM_ENDPOINT_URL="$GPU_BASE_URL/segment"
export SAM_API_KEY="$GPU_API_TOKEN"
export SAM_TIMEOUT=120
export SAM_CLIP_BUDGET=300
export WHISPER_ENDPOINT_URL="$GPU_BASE_URL/transcribe"
export VJEPA_ENDPOINT_URL="$GPU_BASE_URL/embed"
export VJEPA_REVISION='<same-40-character-commit>'
```

**SAM:** `sam.backends.RemoteSegmenter` already matches `/segment`; no adapter
replacement is needed. Its normal sampled-mask effects/tracks remain available.
The separate `/track` route provides actual SAM video propagation for custom
callers through `gpu.clients.Transport(url).call("track", payload)`; the existing
SAM frame interface does not consume video-track responses. Its maximum 120-second
request deadline can expire during a cold download. Defaults of 2 seconds/6 seconds
are particularly likely to fall back. Even raised budgets do not guarantee cold
starts fit; warm the required operation deliberately or accept fallback.

**Audio:** this branch has no remote selector in `audio_ai.analyze`. Use the
signature-compatible adapter explicitly for captions:

```python
from gpu.clients import transcribe
words = transcribe(mono_float32_samples_at_16000_hz)
caption_rows = [word.model_dump() for word in words]
```

To use the existing analyzer's word/hype features and graceful exception fallback,
bind the adapter **once at process startup, before accepting jobs**:

```python
from audio_ai import backends
from gpu.clients import transcribe
backends.transcribe = transcribe
from audio_ai.analyzer import analyze
result = analyze("owned-gameplay.mp4", speech="whisper")
```

This explicit process-wide binding is required; env vars alone do not alter
`audio_ai`. Do not rebind during concurrent jobs. The adapter splits into disjoint
60-second chunks and offsets returned `audio_ai.models.Word` timestamps. Boundary
words can be lost without overlap/alignment; it never retries automatically and
does not return partial words on failure. The analyzer retains its existing
heuristics if transcription fails. `model` and `allow_downloads` compatibility
arguments do not change the remotely configured large-v3 model.

**V-JEPA:** inject the adapter into the existing encoder protocol:

```python
from gpu.clients import RemoteEncoder
from vjepa.features import WindowConfig, extract
encoder = RemoteEncoder()
data = extract("owned-gameplay.mp4", encoder, "full_app/workspace/vjepa-cache",
               WindowConfig(frames=32, fps=8, resolution=256, stride=2), batch_size=1)
# Existing compatible per-game probe:
import vjepa
rows = vjepa.score("owned-gameplay.mp4", enabled=True,
                  head_path="full_app/workspace/valorant-head.npz",
                  game="valorant", encoder=encoder, batch_size=1)
```

`VJEPA_ENDPOINT_URL` is consumed by `RemoteEncoder`, not by the default HFEncoder.
The existing content-addressed cache and identity checks apply. Requests are one
window at a time, even when extract passes a batch; no implicit retries. Remote
failures raise rather than fabricate features. The shared client enforces HTTPS,
blocks redirects, limits responses, and uses a 290-second timeout. SAM retains
its existing transport behavior. Disable SAM with `SAM_BACKEND=fallback`; omit
audio binding and V-JEPA encoder injection to restore local/default behavior.

## Planning costs per minute of footage

[Modal pricing](https://modal.com/pricing), checked 2026-10-12: A100 80GB
$0.000694/GPU-second, CPU $0.0000131/core-second, RAM $0.00000222/GiB-second.
The chosen worker's requested two cores and 16 GiB add at least $0.00006172/second;
actual higher CPU/RAM use, CPU gateway, storage, egress and regional premiums add
cost. The cache volume is listed at $0.09/GiB/month, subject to included usage.

**These throughput assumptions are unmeasured planning ranges**, not benchmarks:

| Operation per minute of source footage | Assumed warm worker seconds | GPU-only cost | GPU + requested worker CPU/RAM |
|---|---:|---:|---:|
| SAM, 240 frames sampled at 4 FPS, 2–8 processed frames/s | 30–120 | $0.021–$0.083 | $0.023–$0.091 |
| Whisper large-v3, 5–20x real time | 3–12 | $0.0021–$0.0083 | $0.0023–$0.0091 |
| V-JEPA, about 30 windows at 2-second stride, 1–3 windows/s | 10–30 | $0.0069–$0.021 | $0.0076–$0.023 |

Formula: `billable_worker_seconds / source_minutes * resource_price_per_second`.
SAM's normal effects request at most 12 masks per clip, so actual cost depends on
clip count and image inference speed; the table assumes full sampled coverage.
SAM video tracking overhead can differ substantially from independent images.
Add **$0.023 per 30-second idle tail** for the worker at requested resources. A
hypothetical 30–180-second cold load adds about **$0.023–$0.136 per cold start**;
initial downloads may take longer. Model switching also costs time. The shared
worker at requested resources continuously busy for an hour is about $2.72,
excluding the other charges above. Scale-to-zero stops compute charges after the
idle tail; cached storage remains. Short isolated calls can cost more in cold
starts/idle time than inference. Measure actual billed seconds on owned footage
before choosing a budget. Client disconnect/timeouts do not guarantee cancellation
of already dispatched GPU work. Do not blindly retry timed-out requests.

## Verification and remaining limits

Offline Linux checks (no GPU/model downloads or paid calls):

```bash
tools/remote_run.sh "pip install -q -r gpu/requirements-test.txt && PYTHONPATH=.:full_app python -m pytest -q gpu/tests"
tools/remote_run.sh "PYTHONPATH=.:full_app python -m pytest -q gpu/tests full_app/tests/test_sam.py full_app/tests/test_vjepa.py full_app/tests/test_audio_ai.py"
```

Tests mock Modal registration and inference, exercise auth/limits/redacted errors,
validate contracts, check SAM tracking session cleanup, and run existing adapters
against mocks. Integration tests generate `testsrc2` and `sine` media with ffmpeg
and verify V-JEPA cache reuse and audio fallback. A CPU-only real Modal SDK import
checks decorator/image construction but does not build an image or deploy it.

Recorded Linux results (2026-10-12):

- Initial install plus `PYTHONPATH=.:full_app python -m pytest -q gpu/tests`:
  18 passed, exit 0; adapter milestone rerun: 25 passed, exit 0.
- Final command
  `tools/remote_run.sh "PYTHONPATH=.:full_app python -m pytest -q -rs gpu/tests full_app/tests/test_sam.py full_app/tests/test_vjepa.py full_app/tests/test_audio_ai.py"`:
  **83 passed, 1 skipped, exit 0**. The existing speech fixture skips because
  `espeak-ng/espeak` is absent. One Starlette/httpx deprecation warning remains.
- `tools/remote_run.sh "VJEPA_REVISION=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa python -c 'import gpu.modal_app' && PYTHONPATH=.:full_app python -m pytest -q gpu/tests full_app/tests/test_sam.py full_app/tests/test_vjepa.py full_app/tests/test_audio_ai.py"`:
  SDK import succeeded, followed by 78 passed/1 skipped at that milestone, exit 0.
  The dummy revision tests registration only; it is not a usable model revision.
  An earlier import command containing a print statement failed with shell-quoting
  `SyntaxError` (exit 1); the corrected command above succeeded. No deployment ran.

Owner acceptance still requires building the GPU image, verifying gated model
access and CUDA libraries, timing cold/warm calls, and assessing SAM mask/track,
Whisper word timing, and embedding quality on owned gameplay. GPU memory and
throughput have not been measured. Tests cannot establish real-model quality or
cloud execution. No automatic app integration was added outside allowed paths;
the explicit adapter bindings above are the supported integration boundary.

Upstream references: [Modal scaling](https://modal.com/docs/guide/scale),
[SAM 3 installation and inference](https://github.com/facebookresearch/sam3),
[faster-whisper GPU and timestamp API](https://github.com/SYSTRAN/faster-whisper),
[Transformers V-JEPA 2](https://huggingface.co/docs/transformers/en/model_doc/vjepa2).
