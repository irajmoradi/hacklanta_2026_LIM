# Extension quickstart and configuration

Commands run from the repository root unless a `cd` is shown. They match the DOC-01 snapshot; see [architecture](architecture.md) for integration boundaries. Shell examples use Bash; PowerShell users should use `curl.exe` rather than the historical `curl` alias.

## Local setup

Install Python 3.10+ and FFmpeg/ffprobe on PATH. Rendering uses libx264/AAC; text/captions need drawtext/libass. A GPU is optional. Node 22 is the Docker build version and a suitable baseline for React.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r full_app/requirements.txt
ffmpeg -version
ffprobe -version
cd full_app
python app.py
```

Configure `GEMINI_API_KEY` in the process environment before starting for analysis/planning. The app also loads a repository-root `.env` without overriding environment values; never commit it. Direct libraries/CLIs generally do not load this file. Uploading and rendering an explicit plan need no key.

PowerShell, from the root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r full_app/requirements.txt
Set-Location full_app
python app.py
```

Open http://localhost:8000 for the simple frontend. In a second shell:

```bash
cd full_app/production_frontend
npm ci
npm run dev
```

Open Vite's printed URL (normally http://localhost:5173). `/api` proxies to the backend on 8000. `npm run build` type-checks and builds `dist/`; local Flask does not automatically serve it. Docker copies the build into Flask's frontend directory.

Upload → analyze/plan → review clips → render → download. Hosted analysis is billable. Game context goes through `prompt`; the HTTP schema has no separate `game` field. Use one backend process per workspace.

## Key-free render check

With the backend running, use another Bash shell at the root. This creates synthetic media under the ignored workspace and renders two seconds without AI stages or paid requests:

```bash
mkdir -p full_app/workspace/doc-smoke
ffmpeg -y -f lavfi -i testsrc2=size=320x180:rate=15 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 3 -c:v libx264 -pix_fmt yuv420p -c:a aac full_app/workspace/doc-smoke/input.mp4
curl --fail --silent --show-error -F video=@full_app/workspace/doc-smoke/input.mp4 http://localhost:8000/api/jobs > full_app/workspace/doc-smoke/job.json
JOB_ID=$(python -c 'import json; print(json.load(open("full_app/workspace/doc-smoke/job.json"))["id"])')
curl --fail --silent --show-error -H 'Content-Type: application/json' -d '{"generate_thumbnails":false,"reactions":false,"edit_plan":{"render_version":2,"resolution":720,"segments":[{"source_start":0,"source_end":2}]}}' "http://localhost:8000/api/jobs/$JOB_ID/render"
curl --fail --silent --show-error "http://localhost:8000/api/jobs/$JOB_ID"
```

Repeat the last GET until `status` is `done`; errors appear in the snapshot. Then:

```bash
curl --fail --silent --show-error "http://localhost:8000/api/jobs/$JOB_ID/download" -o full_app/workspace/doc-smoke/output.mp4
ffprobe -v error -show_entries stream=codec_name,width,height -of json full_app/workspace/doc-smoke/output.mp4
```

The larger offline demo's entry point is `bash full_app/demo/run_demo.sh --output full_app/demo/demo_out --duration 28 --budget 8`. **It is currently broken in this snapshot**: its harness expects the removed `app.WORKSPACE` attribute. Use the render check above until integration repairs it. The demo uses synthetic media, mocked providers and a custom pipeline; it does not establish production wiring. See [demo](e2e.md).

## Docker

With Docker Compose and runtime provider credentials configured, from the root:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f app
docker compose down
```

Visit http://localhost:8000. The image builds React, installs FFmpeg/core Python requirements, and runs Gunicorn as an unprivileged user with one process/four request threads. Job workers are separate threads. The named `workspace` volume persists jobs/media; `down` retains it. Do not use `down -v` unless discarding it intentionally. Port 8000 binds on all interfaces; the API has no authentication/tenant isolation and belongs on a trusted network.

Build extras: `INSTALL_WHISPER=true INSTALL_OCR=true docker compose build app`, or `docker compose build --build-arg INSTALL_SAM2=true app`. These install packages, not model weights. GPU device mapping is not configured. Compose forwards only `GEMINI_API_KEY`, `GEMINI_MODEL`, `GOOGLE_API_KEY`, and `GOOGLE_GENAI_USE_VERTEXAI`; other settings need your own environment override and asset mounts.

## Provider choices

AI Studio uses `GEMINI_API_KEY`. Direct Vertex express providers use `GOOGLE_API_KEY` with `GOOGLE_GENAI_USE_VERTEXAI=true`, but the **job pipeline still requires `GEMINI_API_KEY` or `X-API-Key`**. For the app, set Vertex mode and supply the Vertex express key through the runtime `GEMINI_API_KEY` slot or `X-API-Key`. Setting only `GOOGLE_API_KEY` is insufficient for jobs. Keep credentials out of command history, logs and committed files.

App model default: `gemini-3.1-flash-lite-preview`; direct provider: `gemini-3.5-flash-lite`. These are code defaults, not availability guarantees. Override `GEMINI_MODEL` for your account. Vertex's inline input has a default 20 MiB raw-byte guard; duration chunks may still exceed it. See [providers](video_models.md).

Local analysis needs a vision server supporting multiple images and strict JSON schemas. Set `LOCAL_VLM_URL`, e.g. `http://localhost:8001/v1` (avoid Flask's port), `LOCAL_VLM_MODEL`, and optionally `LOCAL_VLM_API_KEY`; submit `provider: "local"`. It sends timestamped JPEG frames without audio. Automatic edit planning still calls Gemini; explicit plans avoid it.

## Configuration

Tables cover repository application/test/tool environment variables, HTTP flags and Python CLI switches. SDK/platform variables not read/configured by the repository are outside this inventory. Python-only controls are not HTTP options; unknown HTTP fields are rejected.

| Environment variable | Default / meaning |
| --- | --- |
| `GEMINI_API_KEY` | Unset; app key gate, AI Studio, local-analysis Gemini planner |
| `GOOGLE_API_KEY` | Unset; direct Vertex provider/narration; see app limitation above |
| `GOOGLE_GENAI_USE_VERTEXAI` | False; case-insensitive `true` selects Vertex |
| `GEMINI_MODEL` | App/eval `gemini-3.1-flash-lite-preview`; direct provider/narration `gemini-3.5-flash-lite` |
| `JOB_WORKSPACE` | Source-resolved `full_app/workspace`; durable jobs/media |
| `MAX_UPLOAD_BYTES` | `2147483648`; entire multipart request cap |
| `JOB_WORKERS` | `2`; background threads; admission capacity fixed at 32 |
| `LOCAL_VLM_URL` | `http://localhost:8000/v1`; override to a separate inference port |
| `LOCAL_VLM_MODEL` | `local`; served model identifier |
| `LOCAL_VLM_API_KEY` | Unset; optional local server Bearer credential |
| `REACTION_PACK` | Unset; folder with `pack.json`; enables reactions by default when set |
| `SAM_BACKEND` | `fallback`; choices fallback/remote/local |
| `SAM_ENDPOINT_URL` | Empty; remote segmentation URL |
| `SAM_API_KEY` | Empty; remote Bearer credential |
| `SAM_TIMEOUT` | `2`; per-request seconds |
| `SAM_CLIP_BUDGET` | `6`; per-clip budget seconds |
| `SAM2_CHECKPOINT` | Empty; provisioned local checkpoint |
| `SAM2_CONFIG` | `configs/sam2.1/sam2.1_hiera_s.yaml` |
| `SAM2_DEVICE` | `cpu`; local device |
| `VJEPA_ENABLED` | `0`; 1/true/yes enables library inference, not HTTP integration |
| `VJEPA_HEAD` | Unset; trained head; absent head returns no scores |
| `VJEPA_CACHE` | `workspace/vjepa-cache`; inference features |
| `ELEVENLABS_API_KEY` | Unset; TTS additionally needs `allow_network` |
| `NARRATION_CONSENTED_VOICE_ID` | Empty; stock George (`JBFqnCBsd6RMkjVDRZzb`); override attests consent |
| `DISCORD_BOT_TOKEN` | Required for bot |
| `DISCORD_ALLOWED_CHANNEL_IDS` | Required; comma-separated positive channel IDs |
| `DISCORD_API_BASE_URL` | `http://127.0.0.1:8000` |
| `DISCORD_PUBLIC_BASE_URL` | API base; reachable download-link base |
| `DISCORD_VOD_HOSTS` | Empty; exact allowed HTTPS direct-video hosts |
| `DISCORD_MAX_INPUT_BYTES` | `104857600`; bot download cap |
| `DISCORD_MAX_UPLOAD_BYTES` | `10485760`; output attachment cap, bounded by guild limit |
| `DISCORD_USER_COOLDOWN_SECONDS` | `300`; per-user cooldown |
| `DISCORD_POLL_SECONDS` | `3`; polling interval |
| `DISCORD_JOB_TIMEOUT_SECONDS` | `1800`; overall bot job budget |
| `OBS_WEBSOCKET_PASSWORD` | Default variable name in capture's `obs.password_env`; OBS password |
| `INSTALL_WHISPER`, `INSTALL_OCR`, `INSTALL_SAM2` | `false`; Compose variables/Docker build args, not runtime feature toggles |
| `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `PIP_NO_CACHE_DIR` | Docker sets each to `1` |
| `RUNNER_IP` | Fallback `tools/runner_ip`; Linux runner address |
| `RUNNER_KEY` | `$HOME/.ssh/village_vultr`; runner identity |
| `MODEL`, `EFFORT` | Integrator-only `tools/dispatch.sh`: `gpt-6-astra`, `medium`; task dispatch settings, not app settings |
| `PYTHONPATH` | Demo launcher prepends `full_app` |
| `RUN_SIGNALS_BENCHMARK` | Unset; `1` opts into synthetic benchmark |
| `LIM_LIVE_SMOKE` | Unset; `1` opts into marked paid video test |
| `LIM_LIVE_ENV_FILE` | Unset; existing runtime credentials file on test machine, never copied |
| `ENABLE_RENDER_HOOK` | Obsolete; current pipeline does not read it |

`HOME` supplies the runner's default SSH-key directory; never repurpose it. `PATH` must resolve Python/FFmpeg and optional tools. No frontend `VITE_*` setting is read.

| HTTP option / flag | Default / behavior |
| --- | --- |
| `mode` | `nice`; nice/mean |
| `style` | `hype_montage`; also clean_edit/meme_edit/cinematic |
| `provider` | `gemini`; local/local_vlm; custom factory or warned Gemini fallback |
| `use_signals` | `true`; candidate proposals |
| `window_scoring` | `true`; scoring requests per candidate before retries |
| `prompt` | Empty; instructions/game context, up to 8000 characters |
| `splits` | `1`; integer 1–4; provider may further chunk |
| `max_duration` | `180`; planned maximum seconds, 1–3600, not source duration cap |
| `preset` | `landscape`; also vertical/square, default resolution 1080 |
| `captions` | `false`; supplied words/cached transcription; explicit false overrides plan |
| `reactions` | True when `REACTION_PACK` set, otherwise false |
| `sam_reframe` | `false`; subject tracks |
| `sam` | `false`; top-three spotlight freeze |
| `generate_thumbnails` | New API false; legacy render true; paid images/compatibility renderer |
| `edit_plan` | Absent; explicit segments bypass AI stages |
| `attitude`, `edit_style` | Legacy aliases for mode/style |
| `job_id` | Legacy request ID; new API uses path |
| `api_key` | Legacy in-memory credential; prefer `X-API-Key` |
| `keep` | Clip PATCH field, true by default; false excludes clip |
| `after` | SSE cursor alternative to `Last-Event-ID` |

Boolean values must be JSON booleans. `game`, `ocr`, `privacy`, `narration`, `music`, `vjepa`, and `share_kit` are not top-level HTTP options.

## Explicit plan and library controls

| Interface | Fields / flags and defaults |
| --- | --- |
| Render plan | `render_version=2`, required `segments` (1–100), `preset=landscape`, `resolution=1080` (720/1080), `fps=30` (10–60), `reframe=crosshair` (crosshair/motion/blur), `transition=cut` (cut/fast_zoom/whip/flash/glitch), `transition_duration=0.15`, optional intro/outro cards |
| Render segment | Required `source_start`, `source_end`; `video_effects=[]`, `sound_effects=[]`, `title=None`, `sam=None`, `words=[]`; words/tracks clip-local |
| Captions object | `enabled=false`, `transcribe=false`, `model=tiny`, `mask_profanity=false`, configurable profanity list |
| Music object | Required `path`; `volume=0.18`, `beat_sync=false`, `beats=None`, `snap_tolerance=0.25`, `duck=true` |
| ProviderConfig | `chunk_seconds=600`, `overlap_seconds=10`, `fps=2`, `timeout_seconds=120`, `processing_timeout_seconds=300`, `attempts=3`, `backoff_seconds=1`, `input_usd_per_million=None`, `output_usd_per_million=None` |
| Gemini constructor | `media_resolution=low`, `agentic=false`, `cache_ttl_seconds=3600`, `cache_size=32`, `inline_limit_bytes=20971520`; explicit api_key/model/vertexai override environment |
| Local provider | Model/base URL, optional key; `max_frames=32` caps interval sampling |
| Signal Config | `sample_fps=4`, `width=320`, `threads=4`, `scene_backend=auto`, `scene_threshold=0.30`, `ocr=false`, `ocr_width=960`, `ocr_regions=None`, `ocr_cooldown=3`, `peak_threshold=0.65`, `pre_roll=3`, `post_roll=4`, `min_length=3`, `max_length=20`, `merge_gap=1`, `dead_motion=0.008`, `dead_audio=0.012`, `trim_dead_air=true`, `max_candidates=30`; weights scene .15/rms .25/onset .15/sustained .15/motion .30/ocr .70 |
| PlannerOptions | `mode=nice`, `style="hype montage"` (spaces), `target_length=30`, `aspect=16:9`, `min_clip_length=1`, `max_clip_length=6`; explicit optional refiner |
| Share plan.social | video_path/source_path/intro_duration/captions_path/thumbnail_text/subject_cutout/gemini_metadata/gemini_image; network needs supplied client plus enabled flag; [details](social.md) |
| Narration | `allow_network=false`, `character_cap=1000`, optional cache_dir; hype_caster/deadpan_roast/nature_documentary personas |
| Capture JSON | watch/api/options/state/stable_seconds/poll_seconds/retry_seconds/include_existing/hotkey/obs; OBS has url/password_env/timeout; [details](capture.md) |
| PrivacyOptions | `game=valorant`, `backend=auto` (auto/tesseract/rapidocr/none), `own_name=None`, `keep_own_name=false`, `blur_webcam=false`, `sample_fps=2`, `hold_seconds=0.75`, `padding_pixels=5`, `regions=None`, `manual_boxes=[]`; explicitly invoke [library/CLI](privacy.md) |

Typed contracts/ranges are in `full_app/render/plan.py`, `services/video_understanding.py`, `signals/models.py`, `planner/models.py`, and `privacy/models.py`. Library effect parameters are described in [FX](fx.md), [SAM](sam.md), [reactions](reactions.md), [music](music.md), and [multi-POV](multipov.md). Installing them does not create HTTP flags.

## CLI switch inventory

Run Python from `full_app`. Every argparse entry also accepts `-h`/`--help` for types/defaults.

| Entry point | Positional arguments; every custom switch |
| --- | --- |
| `python -m ingest` | source; --cache-dir, --proxy-height, --chunk-seconds, --overlap-seconds, --max-bytes, --max-duration, --owns-content, --chat-log, --twitch-vod-id, --chat-offset |
| `python -m signals` | video; --profile, --ocr, --config |
| `python -m audio_ai` | video; --audio-track, --speech, --whisper-model, --allow-model-downloads, --vad, --yamnet-model |
| `python -m sam` | video output; --start, required --end, --effect, --kill-time, --freeze-seconds, --prompt, --vertical |
| `python -m privacy` | source output; --options, --track |
| `python -m capture` | --config, --watch, --api, --hotkey; mutually exclusive --save-replay, --event, --obs-context |
| `python -m discord_bot` | No custom switches; environment configuration |
| `python -m vjepa.train` | manifest output; --cache, --model, --revision, --device, --tiny, --precomputed, --frames, --fps, --resolution, --stride, --batch-size, --epochs, --seed |
| `python -m fx.contact_sheet` | Required --output; optional --source |
| `python -m reactions.demo` | Optional folder, default reaction_packs/synthetic |
| `python -m perf.bench` | --seconds, --effects, --json |
| `python -m eval.synthetic` | destination |
| `python -m eval.runner` | manifest; --output, mutually exclusive --mock, --replay, --live-smoke; --window-scorer |
| `python -m demo.make_demo_gameplay` | --output, --duration |
| `python -m demo.pipeline` | --output, --duration, --budget; root demo/run_demo.sh launcher forwards these |

URL ingest requires `--owns-content`; optional import tools are in [ingest](ingest.md). Live eval and `--allow-model-downloads` opt into network. V-JEPA `--tiny` is a test stand-in, not a trained gameplay model.

## Extras and checks

Base install needs no torch, Whisper or SAM weights. From `full_app`, install only needed extras:

| Feature | Install / provisioning |
| --- | --- |
| Captions | `python -m pip install -r render/requirements-captions.txt`; separately cache model |
| Audio speech/events | `python -m pip install -r audio_ai/extras/speech.txt` or `-r audio_ai/extras/events.txt`; local YAMNet SavedModel |
| Local SAM | `python -m pip install -r sam/requirements-local.txt`; separate checkpoint/config |
| Privacy RapidOCR | `python -m pip install -r privacy/requirements-rapidocr.txt`; Tesseract CLI alternative |
| Share kit | `python -m pip install -r social/requirements.txt` |
| Discord | `python -m pip install -r discord_bot/requirements.txt` |
| Capture/hotkey | `python -m pip install -r capture/requirements.txt`; optional `-r capture/requirements-hotkey.txt` |
| V-JEPA | [Extras/training](vjepa.md); disabled without trained head |

From the root on the Linux runner (SSH, rsync, RUNNER_IP or tools/runner_ip, RUNNER_KEY or default identity):

```bash
bash tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"
bash tools/remote_run.sh "python -m pytest -q docs/README_ASSETS/test_documentation.py"
bash tools/remote_run.sh "cd full_app/production_frontend && npm ci && npm test && npm run build"
```

The runner installs core requirements and pytest, not nested extras. Missing extras can skip tests or cause setup failures. Live calls are unnecessary for documentation checks. Authorized live tests must stay within three Gemini calls per task, without copying credentials into the checkout or runner. See [live tests](video_models.md).

Troubleshooting: inspect `/api/info`, job warnings/errors and SSE; check FFmpeg filters; give local VLM a different port; disable thumbnails for offline use; provision cached weights for captions. Workspace ownership errors indicate another process uses that directory. Check [integration boundaries](architecture.md) before assuming an installed module is enabled in the UI.
