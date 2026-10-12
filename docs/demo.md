# DEMO-01: real Valorant walkthrough

This run uses the `ext/DEMO-01` worktree, based on Extension commit `2a7c565`.
Only `demo_video/**` and this document are changed. The production backend,
frontend and providers remain as checked out at that commit.

## Run design

- Source: runner `/srv/demo_in/valorant_phoenix_44k.mp4`, 1,871.970 seconds,
  1920 x 1080, 60 fps. The owner supplied the gameplay and old montages.
- Real multipart upload to `POST /api/jobs`; real React frontend and Flask
  durable queue. Playwright uses Chromium at 1920 x 1080, without mocked routes.
- Auto game detection, local gameplay signals, Gemini window scoring, local
  story planner, team reactions, privacy and share kit enabled. Speech captions
  and optional model downloads disabled.
- Motion is sampled at 2 fps; OCR is bounded to one sample every five seconds
  after an unbounded OCR attempt proved slow. This may miss brief kill-feed
  events. Audio still spans the full match. Neither aborted attempt made a
  Gemini call.
- The latest user instruction limits this run to **three live Gemini attempts**,
  overriding the task record's 120-call allowance. `budget.py` reserves attempts
  before SDK calls, persists across restarts and disables SDK/provider retries.
  Never delete the ledger to retry this task. Failed requests consume budget.
- The initial candidate request succeeded at source resolution, but its following
  full-match attempt hit a local SDK schema error. The final successful run uses
  one combined structured request for full-match clips plus assessment of the
  strongest candidate. A complete-match
  640-pixel, 2 fps, approximately 55 kb/s video + 16 kb/s mono audio proxy keeps
  the full-video request inside Vertex Express's inline size limit. Rendering
  uses the original 1080p source. Fine HUD details are weaker in this proxy.
  The `whole_video` stage reuses the combined response; its near-zero timing is
  not the model's inference time. That time is reported under `window_scoring`.
- Mean mode is a local alternate story plan of the selected moments, submitted
  as an explicit plan to the render API. It is not a separate Gemini lowlight
  analysis. No additional paid calls are needed for renders or share kits.

## Demo-only adapters and discovered issues

These are in `demo_video/live_smoke_server.py`; none is a claimed core fix.

1. **Auto detection / signal profile mismatch.** On this source, the automatic
   detector returned `('generic', 0.0)` after 5.5072 seconds in the first attempt.
   `signals.ocr.regions_for('generic', None)` raises
   `ValueError: unknown game profile: generic`. The API reported exactly
   `analyze failed (ValueError); check configuration and retry`.
   That attempt made zero Gemini calls. The demo records the original detection
   and falls back to the owner-supplied Valorant label with an explicit warning.
   Core needs a safe generic mapping and improved real-footage detection.
2. **Frontend capability/option contract.** `/api/info` does not provide
   `frontend_capabilities`. The UI consequently disables privacy, story planner
   and share-kit controls although backend modules exist. The demo advertises
   only supported features and translates `planner_v2` → `planner`,
   `privacy_blur` → `privacy`, `share_kit` → `social`; game selection also enables
   `profiles`. Core needs matching discovery and option names.
3. **Review/share payload contract.** Backend status has no `interest_curve`,
   while `share_kit` is a directory marker string rather than the UI's object.
   The adapter derives a sparse curve from actual candidate midpoint scores and
   exposes actual generated metadata, chapters, covers and download links.
   This is candidate evidence, not a dense per-frame interest measurement.
4. **Privacy cost.** The core sanitizes the entire source before editing.
   The demo opts into the existing `backend=none` conservative region fallback
   and caches its result by source path/size/mtime and privacy options. This is
   HUD-region blur, not precise name-only detection; it cannot preserve the
   uploader's name. Review the outputs before publishing.
5. **Mode changes invalidate analysis.** Changing `mode` clears clips and
   candidates. An explicit local mean-mode plan avoids another paid analysis;
   the prior selected-clip evidence is retained in `mean_editorial_input.json`.
   Mean rendering then chooses roast reactions without per-clip classification.
6. **Gemini SDK schema construction fails before transport.** The original
   `ClipList` request raised `ValidationError: 2 validation errors for Schema`:
   `properties.clips.items.properties.end.exclusiveMinimum` and
   `properties.clips.items.properties.end_seconds.exclusiveMinimum`, each with
   `Extra inputs are not permitted [type=extra_forbidden, input_value=0, input_type=int]`.
   The core then hid this as `Video analysis failed`. `diagnose_schema.py`
   reproduced it with a mocked transport. The demo sends a JSON schema with
   inclusive minimum constraints and retains strict original Pydantic response
   validation, including rejection of zero-length or nonpositive-ending clips.
   Core needs an SDK-compatible schema and safe, actionable error reporting.

## Reproduction

From the Windows task worktree, with the configured SSH key and runner inputs:

```powershell
bash tools/remote_run.sh "python -m pytest demo_video/test_demo.py -q && cd full_app/production_frontend && npm ci --silent && npm run build && npx playwright install chromium"
python demo_video/launch_live.py
ssh -i "$env:USERPROFILE/.ssh/village_vultr" root@104.207.133.47 "cd /srv/lim/lim-demo01 && node demo_video/record_ui.cjs"
ssh -i "$env:USERPROFILE/.ssh/village_vultr" root@104.207.133.47 "cd /srv/lim/lim-demo01 && .venv/bin/python demo_video/finish_run.py && .venv/bin/python demo_video/assemble.py"
python demo_video/collect.py
```

`launch_live.py` is explicitly a live smoke launcher. It reads only
`GOOGLE_API_KEY` at runtime from `C:/Users/mourn/Downloads/hacklanta/.env` and
passes it over SSH stdin into the backend process environment. No credential is
written to files, command arguments or logs. The provider explicitly selects
Vertex Express and `gemini-3.5-flash-lite`. The service binds runner loopback
port 8011; SSH forwarding can expose it locally for review.

The runner worktree is disposable. `remote_run.sh` uses `rsync --delete`, so run
it before launching the backend, or after the recordings/renders finish: it can
remove the runner-only reaction pack and frontend build. Launching copies the
owner's reaction pack into `full_app/reaction_packs/team/` on the runner only.
The pack, source footage, keys, caches and final media are never committed.

## Outputs and evidence

Runner output root: `/srv/demo_out/demo01/`. Local deliverables:
`demo_video/out/` (gitignored). `collect.py` copies only an explicit allowlist;
it does not copy the source gameplay, job workspaces or full-source privacy cache.

- `extension_demo.mp4`: assembled 1080p walkthrough, comparison and output cuts.
- `montage_landscape.mp4`, `montage_vertical.mp4`, `montage_mean_vertical.mp4`.
- `ui_walkthrough.mp4`: edited UI recording with long processing waits removed.
- `contact_sheet.jpg`, `frontend.png`.
- `share_landscape/`, `share_vertical/`, `share_mean_vertical/`.
- `evidence.json`: stage timings, candidate counts and positive signal counts.
- `clip_signals.csv`: per-clip source ranges, descriptions, scores, signals/events.
- `analysis.json`, `landscape.json`, `vertical.json`, `mean_vertical.json`:
  actual API snapshots; `profile_detection.json`: original automatic result.
- `live_calls.json`: persistent attempt ledger; `output_manifest.json`: actual
  output durations, dimensions and sizes; `ui_scenes.json`: recording edit list.

Final measured results and verification are filled in after the run completes.
