# Evaluation, containers, and CI (EXT-08)

Run from `full_app/` with Python 3.12 and ffmpeg/ffprobe on PATH:

```sh
python -m eval.synthetic /tmp/lim-eval
python -m eval.runner /tmp/lim-eval/labels.json --mock --output /tmp/lim-eval/report.json
python -m pytest -q eval
```

From a sprint worktree on Windows, use the Linux runner:

```sh
bash tools/remote_run.sh "cd full_app && python -m pytest -q eval"
```

The generated six-second testsrc2 videos have sine audio, visible white bursts at
1–2 and 4–5 seconds, and a negative example. They test plumbing, not gameplay
quality. No media or weights are checked in. Generate outputs outside the checkout.
Mock predictions are fixed independently of labels, and the report says `mode: mock`.

## Labelled set, predictions, and metrics

The UTF-8 JSON manifest has this shape; paths resolve relative to the manifest:

```json
{
  "version": 1,
  "videos": [
    {
      "id": "match-01",
      "path": "videos/match-01.mp4",
      "duration_seconds": 60,
      "highlights": [{"start": 10, "end": 15}, {"start": 30, "end": 35}]
    }
  ]
}
```

IDs must be unique, duration positive, video files present, and intervals finite
seconds satisfying `0 <= start < end <= duration`. Empty highlight lists represent
negative footage. Labels treat highlights and lowlights as one notable-moment class.
Duration is supplied by the dataset author; the loader does not decode every video.

Predictions contain `start`, `end`, and a numeric `score` (higher ranks first).
Pydantic objects and application `start_seconds`/`end_seconds` fields are accepted.
`hype` is accepted as a score alias. If confidence is absent, score defaults to 1
and input order breaks ties: AP then measures that order, not model confidence.
Invalid outputs fail that video and produce a nonzero CLI exit, not silent clipping.

- Temporal IoU is intersection duration divided by union duration. At IoU 0.3
  and 0.5, predictions sorted by confidence greedily match the best unmatched
  ground-truth interval. Each label can match once; duplicates are false positives.
- Precision, recall, and F1 aggregate TP/FP/FN across videos (micro averages).
  Zero denominators produce zero, including empty/empty per-video metrics.
- AP integrates the all-points interpolated precision envelope over recall.
  `mAP` at each threshold averages per-video AP over videos with labels; negative
  videos contribute false positives to precision but are excluded from mAP.
  Top-level mAP averages the two thresholds, **not** COCO mAP@0.5:0.95.
- Time-to-first-clip is elapsed wall time from pipeline invocation, including
  uploads/preprocessing. Batch providers expose clips only at completion, so this
  defaults to completion time. An adapter can supply a measured earlier value.
  No detections yield null; means include only videos returning clips, with the
  denominator available as `videos_with_clip`. This does not measure montage rendering.
- Cost per footage minute is total USD / total input minutes, not an average of
  per-video ratios. Missing provider cost remains null, never zero. Zero means a
  local/mock path with no API charge, excluding hardware cost. There are no hardcoded
  token prices; adapters supply billed or explicitly estimated USD.

Reports retain predictions, per-video metrics, elapsed time, skipped IDs/reasons,
and error types. Summaries include successful videos only. Check `status` and video
counts before comparing partially available pipelines. Error messages are omitted
to avoid leaking provider credentials. Skips exit 0; execution/validation errors exit 1.

## Pipeline integration

```sh
# No paid calls: existing local modules run; missing integrations are explicit skips.
python -m eval.runner /path/to/labels.json --output /tmp/comparison.json

# Evaluate saved outputs without contacting any provider.
python -m eval.runner /path/to/labels.json --replay /path/to/predictions.json
```

Replay JSON is `{pipeline_name: {video_id: output}}`, where pipeline names are
`gemini-only`, `signals-only`, and `signals-vlm`, and an output is, for example:

```json
{"clips": [{"start": 10, "end": 15, "score": 0.9}], "cost_usd": 0.002}
```

Replay reports measure replay overhead, not historical provider latency. Historical
`time_to_first_clip_seconds` fields are deliberately discarded. Use the Python API
for latency benchmarks: `eval.runner.evaluate(dataset, {name: callable})`.
Callables receive only ID, path, and duration, **never labels**, and return the output
above (or a clip list when cost is unknown).

Built-in integrations are deliberately lazy:

- `gemini-only` wraps existing `services.gemini_client.GeminiVideoClient`, using the
  same clip-finder prompt and file cleanup behavior. It skips unless an injected
  mock client or the explicit live smoke flag is supplied.
- `signals-only` imports `signals.detect_candidates(video_path)` (EXT-01).
- `signals-vlm` calls that detector, then imports the optional offline/local hook
  `services.eval_adapter.score_windows(video_path, candidates)`. Alternatively pass
  `--window-scorer your_module:your_function`. The hook returns the same output
  dictionary, normalizing provider-specific window scores to `score`. Import failures
  or missing hooks skip gracefully; inference errors fail rather than masquerading
  as missing dependencies. The EXT-02 provider interface is not in this checkout,
  so its integrator must supply this thin hook or a custom callable. Hooks are trusted
  local/mock code and must not make paid calls. Do not use them to bypass the live budget.

### Optional live smoke (never CI)

`python -m eval.runner labels.json --live-smoke` enables the legacy AI Studio Gemini
adapter using runtime `GEMINI_API_KEY`; datasets over three videos are rejected
before any call, with a second per-adapter three-call cap and no harness retries.
Legacy cost remains unknown because its return value has no usage metadata.
This adapter is for the current client; it does not reinterpret a Vertex Express key
as an AI Studio key. `GOOGLE_API_KEY`/Vertex requires the EXT-02 provider integration
or an explicitly budgeted external live smoke whose outputs can then be replayed.
No live calls were needed for EXT-08 validation, and no key file was read.

## Docker

From repository root:

```sh
docker compose up --build
# Visit http://localhost:8000
```

The multi-stage image builds React with Node 22 and serves its compiled assets
through Flask on Python 3.12 with ffmpeg. Gunicorn uses one process and four threads
because the current app stores jobs in memory. The container runs as UID 10001.
The named `workspace` volume persists media; legacy in-memory job IDs do not survive
restarts until EXT-03 is integrated. The healthcheck queries `/api/info`.
Credentials are runtime environment variables; `.env`, videos, weights, and local
build/cache directories are excluded from the build context. Compose passes Vertex
environment variables through for future provider integration; the current app
uses `GEMINI_API_KEY`. No key is needed for container startup.

Optional packages default off:

```sh
docker compose build --build-arg INSTALL_WHISPER=true --build-arg INSTALL_OCR=true
docker compose build --build-arg INSTALL_SAM2=true
```

Whisper installs faster-whisper; OCR installs Tesseract, pytesseract and RapidOCR;
SAM2 installs the Python package with CUDA extension build disabled. These flags
install dependencies only: feature hooks, downloaded model weights, and GPU runtime
configuration remain the corresponding sprint modules' responsibility. Model weights
are never included in the image. SAM2/Whisper can substantially increase image size.

## CI

`.github/workflows/extension.yml` runs on pushes and PRs targeting `Extension`, plus
manual dispatch. It installs ffmpeg, runs pytest with `-m 'not live'` and
`pytest-socket --disable-socket`, generates/evaluates synthetic fixtures with mocks,
builds the frontend, uploads the eval JSON, and builds/smoke-tests the default image.
No secrets are referenced and provider-key environment variables are empty.
GitHub execution occurs after integration; local validation commands and limitations
are recorded in the task's final report.

## Validation in this task worktree

- `bash tools/remote_run.sh "cd full_app && python -m pytest -q eval && python -m eval.synthetic /tmp/lim-ext08-eval && python -m eval.runner /tmp/lim-ext08-eval/labels.json --mock --output /tmp/lim-ext08-eval/report.json && python -m eval.runner /tmp/lim-ext08-eval/labels.json --output /tmp/lim-ext08-eval/optional-report.json && cd production_frontend && npm ci && npm run build"`
  exited 0: the initial 18 metric/harness tests passed, both CLI modes completed,
  and Vite built the production bundle.
- `bash tools/remote_run.sh "python -m pip install -q pytest-socket && cd full_app && python -m pytest -q -m 'not live' --disable-socket"`
  exited 0 with 18 tests. After adding the application regression,
  `bash tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live' --disable-socket"`
  exited 0 with **19 passed**. The added test uploads synthetic media, mocks Gemini
  analysis/planning, renders with real ffmpeg, and downloads the result.
- `docker compose config --quiet` and `docker build -t lim-ext08:test .` exited 0.
  The image ran locally with `docker run -d --name lim-ext08-smoke -p 127.0.0.1:18008:8000 lim-ext08:test`.
  PowerShell `Invoke-WebRequest` checks asserted HTTP 200 for `/api/info`, `/`, and
  the index's JavaScript asset; `docker inspect --format '{{.State.Health.Status}}' lim-ext08-smoke`
  returned `healthy`. The temporary container was removed; smoke checks exited 0.

The runner preflight's `command -v docker` exited 1 because Docker is absent there;
container validation used local Linux containers instead. The actual workflow has
not run on GitHub, and optional ML image variants have not been built. npm reported
an existing damaged-lockfile warning and eight dependency vulnerabilities (one low,
one moderate, five high, one critical); install and build still succeeded. Frontend
dependency updates are outside EXT-08's allowed paths and remain for integration.
