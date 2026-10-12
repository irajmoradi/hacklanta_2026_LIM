# SAM effects and reframe assistance (EXT-07)

This opt-in package exposes effects and tracking to the render/reframe integrator.
It does not change Flask routes, Gemini planning, effect schemas, or existing render
defaults: those files are outside EXT-07's allowed paths. No model weights, torch,
GPU, credentials, or network requests are required for the default backend.

## Try it

Install `full_app/requirements.txt`, and have `ffmpeg` and `ffprobe` on PATH. From
`full_app`, run:

```sh
python -m sam input.mp4 pulse.mp4 --end 5 --effect outline_pulse
python -m sam input.mp4 freeze.mp4 --end 5 --effect spotlight_freeze --kill-time 2 --freeze-seconds .6
python -m sam input.mp4 vertical.mp4 --end 5 --effect background_blur --vertical
```

The fallback runs motion and border-color saliency on small frames, selects a
connected subject region, and uses a stable central ellipse if the scene is blank.
It is a heuristic, not semantic player/enemy recognition; HUD elements or camera
motion can confuse it. No external media are needed to run the tests below.

```python
import sam

# Absolute source timestamps; normalized geometry, top-left image origin.
track = sam.subject_track("input.mp4", 1, 5)
# [(t, cx, cy, width, height), ...], one tuple per source frame in the clip.

sam.render_effect("input.mp4", "out.mp4", 1, 5,
                  effect="spotlight_freeze", kill_time=2,
                  prompt="player character")
```

For scripts that select a model backend, put calls behind
`if __name__ == "__main__":` because workers use multiprocessing spawn. The CLI
already does this. `Config(...)` can override environment configuration per call.
The backend interface is `segment(rgb_uint8_frame, prompt, seed_mask) -> mask`;
adapters live in `sam/backends.py`. `sam.effects.composite` is a pure BGR frame
compositor for renderers that already own decoding and encoding.

## SAM 3 endpoint adapter

Set `SAM_BACKEND=remote`, `SAM_ENDPOINT_URL=https://your-host/segment`, and optionally
`SAM_API_KEY` in the environment. Requests use `Authorization: Bearer <key>`.
This is a documented adapter contract for a service you operate; it is not a claim
that all SAM 3 providers share an API. The service must run its own text-prompted
model and translate its outputs to this contract:

```json
{"image_png": "<base64 RGB PNG>", "prompt": "player character"}
```

POST JSON to the configured URL. Prompts such as `enemy` and `weapon` are passed
unchanged. Return HTTP 200 and JSON:

```json
{"mask": [[0, 0, 1], [0, 1, 1]]}
```

The example only illustrates the schema: the binary array must match the submitted
image's exact height and width. Foreground is 1 (255 also accepted); background is
0. Empty masks, wrong dimensions, nonfinite values, nonbinary masks, malformed
JSON, HTTP errors, and responses over 2 MB trigger fallback. Frames are resized
to at most 256 pixels on the long edge; masks upscale with nearest-neighbor
sampling. Use HTTPS for a deployed service; plain HTTP is used only by offline
loopback tests. Keys are not written to disk or included in diagnostic exceptions.

## Local SAM 2 / SAM 2.1 small (optional)

Follow the [official SAM 2 installation and checkpoint guide](https://github.com/facebookresearch/sam2#installation).
It documents Python >=3.10, PyTorch >=2.5.1 and torchvision >=0.20.1, and recommends
WSL for Windows. Install the appropriate PyTorch build first; then, from `full_app`:

```sh
pip install -r sam/requirements-local.txt
export SAM_BACKEND=local
export SAM2_CHECKPOINT=/absolute/path/to/sam2.1_hiera_small.pt
export SAM2_CONFIG=configs/sam2.1/sam2.1_hiera_s.yaml
export SAM2_DEVICE=cuda
export SAM_TIMEOUT=20
export SAM_CLIP_BUDGET=60
```

Obtain weights separately from upstream; this package never downloads weights.
For SAM 2 small use its corresponding checkpoint and
`SAM2_CONFIG=configs/sam2/sam2_hiera_s.yaml`. Local SAM 2 uses the fallback region's
box as its spatial prompt. It does **not** interpret text; semantic text selection
belongs to the remote backend. The model persists for one clip in an isolated
worker. Missing package, unavailable device, bad weights, or slow initialization
all fall back. The optional requirements file lives under `sam/` so the Linux
runner's root `requirements*.txt` glob does not install heavyweight dependencies.

## Timing, caching, output, and cost

- Default backend is `fallback`. Model calls have a 2-second deadline including
  worker startup (`SAM_TIMEOUT`); cumulative model wait has a 6-second per-clip
  budget (`SAM_CLIP_BUDGET`). A timeout/error terminates the worker and disables
  model calls for the rest of that clip. Normal media processing still takes time;
  the SAM budget does not impose a whole-render deadline. Encoding defaults to
  a separate 120-second timeout, probing to at most 10 seconds.
- Clips sample approximately 4 masks/second, at most 12 uniformly spaced masks.
  `Config(max_samples=...)` permits 1–240. Effects use the nearest sampled mask;
  tracks interpolate boxes, smooth with a 150 ms time constant, and limit pan/size
  velocity to 0.6 normalized units/second. This reduces jitter but can lag fast
  action and does not guarantee the entire subject fits a narrow vertical crop.
- Masks are cached per clip in a process-local LRU (16 clips / 32 MiB), keyed by
  source path, size, nanosecond mtime, time range, prompt, and configuration. No
  cache files or keys are persisted. Read-only arrays prevent caller mutation.
  `sam.clear_cache()` permits retry after a transient provider failure. Changing
  checkpoint contents at the same path also requires clearing the cache.
- Requested ranges select source frames in `[start, end)` and clamp to video end.
  Track timestamps remain absolute; rendered clips start at zero. This version
  assumes constant frame rate and uses the decoder's reported FPS. Normalize VFR
  footage before using it. Effects preserve decoded frame count, except a freeze
  inserts `round(freeze_seconds * fps)` frames after the kill frame. The freeze
  darkens/blurs the background, keeps the cutout sharp, adds glow and a growing-to-
  settled `SICK KILL` text slam, then resumes original playback. Text uses OpenCV's
  Latin font; custom text should be ASCII.
- Existing audio is trimmed/rebased and encoded as stereo AAC. A freeze inserts
  silence at exactly the matching frame boundary, preserving subsequent sync.
  Silent sources stay silent. Output is H.264/yuv420p MP4; vertical output defaults
  to 720x1280 and follows the smoothed center. Odd source dimensions round down
  to even dimensions. Temporary encodes are cleaned and output replaced only on
  success. Invalid media and encoder failures raise; only SAM failures fall back.
- Fallback has no provider cost. Local SAM 2 uses your CPU/GPU resources. Remote
  cost is service-specific: at most `max_samples` requests per uncached clip
  (default 12), with no retries, and fewer if the deadline/budget trips. There is
  no Gemini call in this package. Tests only use local synthetic media and a
  mocked loopback service; no paid live smoke test was run.

## Validation

From the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_sam.py"
```

Tests generate synthetic motion with ffmpeg `drawtext` and `sine`, check mask
shape/content and cache reuse, track movement and smoothness, mock the remote
contract and malformed/slow responses, exercise missing local dependencies,
decode all effects, verify duration/dimensions/audio (including silence insertion),
and check compositor pixels, silent input, final-frame freezes, and atomic output.
Real SAM 3 quality and GPU SAM 2 inference require separately provisioned models;
they are not established by these offline tests.
