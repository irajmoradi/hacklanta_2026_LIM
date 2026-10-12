# FIX-4 completion report

Branch: `ext/FIX-4`. Implementation milestone: `2877cd9`. No push or merge.
The completion commit includes the final compatibility fixes, regression coverage,
stock smoke launcher, measured evidence and documentation.

## Delivered

- Safe generic/League OCR and privacy profiles; stronger distributed HUD/OCR
  detection; optional three-frame budgeted VLM fallback and confidence.
- Backend capability discovery and matching UI/API aliases; game/profile wiring,
  team multipart route compatibility and automatic team processing.
- Dense fused interest curves and structured, downloadable share kits.
- Selected-range privacy with per-range caching, source-clock restoration,
  narrow default HUD coverage and explicit OCR opt-in.
- Mode-only local replanning that retains analysis and avoids stale UI plans.
- SDK-compatible schemas, strict per-item response admission, tolerant model
  timestamp bounds and safe actionable provider errors.
- Configurable durable per-job generation limits, conservative retry reservations,
  bounded parallel top-N scoring, request pacing and stock Vertex inline proxies.

## Verification

Final Python result: **1009 passed, 21 skipped in 521.19 seconds; exit 0**.

```powershell
bash tools/remote_run.sh 'cd full_app && python -m pytest -q > /tmp/fix4-pytest-final.log 2>&1; result=$?; tail -n 100 /tmp/fix4-pytest-final.log; exit $result'
```

Frontend: **27 tests passed, TypeScript check and Vite production build passed;
exit 0**.

```powershell
bash tools/remote_run.sh 'cd full_app/production_frontend && npm test && npm run build'
```

Additional successful focused runner commands:

```powershell
# 48 passed; exit 0
bash tools/remote_run.sh 'cd full_app && python -m pytest tests/test_fix4.py tests/test_video_understanding.py -q'

# 69 Python tests, 26 frontend tests and build passed; exit 0
bash tools/remote_run.sh 'cd full_app && python -m pytest tests/test_fix4.py tests/test_game_profiles.py tests/test_privacy.py -q && cd production_frontend && npm test && npm run build'
```

Earlier runs were not green: the first focused collection stopped with remote
exit 2 on an edit-script UTF-8 corruption (repaired); the next focused run had
132 passes and one stale agentic-schema assertion (updated to the new request
contract), exit 1. The first full run had **996 passed, 9 failed, 21 skipped**,
exit 1: four assertions about an unnecessary intentional-mask warning and five
standalone provider tests missing a job directory. The final implementation
suppresses that misleading warning and preserves standalone provider construction
while real jobs retain durable budgets. Tests mock providers or block network;
optional/live tests are skipped unless explicitly enabled.

## Real smoke

Executed `python docs/fix4_launch_live.py`, exit **0**; the same launcher now
lives at `full_app/tests/launch_fix4_live.py` to follow the module-location rule.
Its only relocation change is the repository-root lookup. It ran the stock
HTTP API and isolated worker on the first **360.000 seconds** of the supplied
Valorant source, with Vertex express credentials passed only through runtime
stdin/environment. No demo adapters or paid test retries.

- Valorant detection confidence **0.909**.
- **14 candidates**, **2 assessed windows**, **13 retained clips**, **360 curve points**.
- **Exactly 3 generation attempts** total; nice/mean render and mode change
  consumed zero additional calls.
- Both exports fully decoded: **8.021333 s, 1920x1080, 30 fps, H.264/AAC**.
- Each share kit had **5 downloadable artifacts**.
- Privacy: **18.8055 s** initially, **1.0485 s** with cache reuse on mean mode.

[Measured summary](fix4_smoke_results.json) and [demo details](demo.md) preserve
results and limitations. Runner artifacts: `/srv/demo_out/fix4/`. The smoke
server has stopped. No footage, generated media, weights or credentials are
committed; the locally inspected frame is in ignored workspace storage.

## How to try

Start `python app.py` from `full_app/` with credentials in the environment.
For Vertex express set `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_API_KEY` and
an available `GEMINI_MODEL`. Start `npm run dev` in
`full_app/production_frontend/`; its `/api` proxy targets port 8000.
Upload footage, select Auto-detect, enable story planner/privacy/share kit,
analyze and render. Switch nice/mean and export again to reuse analysis.
The API accepts the same controls via `game=auto`, `planner=true`,
`privacy=true`, `social=true`. See [pipeline configuration](pipeline.md).

The explicit smoke launcher resumes its existing job and durable ledger;
do not delete it to obtain more calls for this task.

## Remaining limits and choices

The user's three-call ceiling overrides the task record's 30-call smoke limit.
Both assessed windows were correctly vetoed by their reported player-not-alive
state, leaving 12 unscored local clips and one whole-video clip, all good-labeled.
Both mode plans selected the same source ranges and changed the closing caption.
This is an infrastructure/reuse smoke, not proof of unattended highlight/roast
accuracy. The existing deterministic planner underfilled its 30-second target.
Default privacy does not cover central nameplates or scoreboards and can mask
parts of the HUD broadly; explicit custom regions/OCR remain available. Detection
confidence is heuristic, and compressed inline proxies can lose fine HUD detail.
URL/music/chat upload routes remain unadvertised because they are absent.

## Files changed

- `docs/FIX-4-report.md`
- `docs/demo.md`
- `docs/fix4_smoke_results.json`
- `docs/pipeline.md`
- `full_app/pipeline/extensions.py`
- `full_app/pipeline/orchestrator.py`
- `full_app/pipeline/privacy_ranges.py`
- `full_app/pipeline/providers.py`
- `full_app/pipeline/ranking.py`
- `full_app/pipeline/rendering.py`
- `full_app/privacy/detector.py`
- `full_app/privacy/profiles.py`
- `full_app/production_frontend/src/App.tsx`
- `full_app/production_frontend/src/api.test.ts`
- `full_app/production_frontend/src/api.ts`
- `full_app/production_frontend/src/components/EditSettings.tsx`
- `full_app/production_frontend/src/features.test.tsx`
- `full_app/profiles/data/valorant.json`
- `full_app/profiles/detection.py`
- `full_app/server/api.py`
- `full_app/server/capabilities.py`
- `full_app/server/legacy.py`
- `full_app/server/queue.py`
- `full_app/server/resources.py`
- `full_app/server/stage_worker.py`
- `full_app/server/validation.py`
- `full_app/services/call_budget.py`
- `full_app/services/gemini_client.py`
- `full_app/services/provider_errors.py`
- `full_app/services/response_schema.py`
- `full_app/services/video_understanding.py`
- `full_app/signals/detector.py`
- `full_app/signals/fusion.py`
- `full_app/signals/models.py`
- `full_app/signals/ocr.py`
- `full_app/tests/launch_fix4_live.py`
- `full_app/tests/live_fix4_smoke.py`
- `full_app/tests/test_fix4.py`
- `full_app/tests/test_game_profiles.py`
- `full_app/tests/test_int02.py`
- `full_app/tests/test_video_understanding.py`
