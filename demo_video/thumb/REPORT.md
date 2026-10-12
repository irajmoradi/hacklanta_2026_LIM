# THUMB-1 live evidence

Branch: `ext/THUMB-1`. Implementation milestone: `db215e7`.
Generated assets are intentionally untracked in `demo_video/thumb/out/` and
also available on runner 1 at `/srv/lim/lim-thumb1/demo_video/thumb/out/`.

Changed files:

- `full_app/services/gemini_client.py`: configurable image model, validated image
  output, explicit PNG references and dual attempt budgets without retries.
- `full_app/social/__init__.py`: two-candidate exports, selection, job warnings.
- `full_app/social/image_candidates.py`: prompts, local fallback evidence,
  consented reaction extraction and durable image ledger.
- `full_app/social/thumbnails.py`: square size and scene-preserving composition.
- `full_app/tests/test_social.py`, `full_app/tests/test_thumb.py`: offline tests.
- `docs/social.md`: options, adapter contract, integration lines and usage.
- `demo_video/thumb/.gitignore`, `live_smoke.py`, `run_live.ps1`, `REPORT.md`:
  bounded live demo, local recomposition and evidence.

## Result

Vertex express (`genai.Client(vertexai=True, api_key=...)`) rejected
`gemini-3.1-flash-image-preview` as unavailable. The replacement
**`gemini-3.1-flash-image` worked** and is the configurable default through
`GEMINI_IMAGE_MODEL`.

Exactly **7 live image attempts** were reserved in the durable run ledger:

| Attempt | Result |
| --- | --- |
| 1 | Original preview model unavailable; no generated image |
| 2-3 | Valorant candidates 1 and 2 generated |
| 4-5 | Deadlock quota failures, reported as local fallbacks |
| 6-7 | After cooldown, Deadlock candidates 1 and 2 generated |

There were no hidden application or SDK retries. The run limit was eight;
Valorant used two job image slots, Deadlock used four including failed requests.
No further live calls were made to improve composition. The initial smoke exited
1 because Deadlock fell back; `-RetryFailed` exited 0 with both games generated.
The output report preserves the previous failed candidate evidence.

## Inputs and outputs

| Game / mode | Video source | Selected video frame | Consented reaction |
| --- | --- | --- | --- |
| Valorant / nice | `/srv/demo_out/demo02/automatic_montage_landscape.mp4` | 8.5 seconds | `iraj-hype.alpha.webm`, 0.48 seconds |
| Deadlock / mean | `/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4` | 125.5 seconds | `lance-bruh.alpha.webm`, 0.512 seconds |

Each game has `candidate_{1,2}_{youtube,vertical,square}.jpg`: twelve final JPEGs
total, at 1280x720, 1080x1920, and 1080x1080. Master images, gameplay frames and
reaction references are retained for review. `out/report.json` records provenance,
warnings, sizes, title bounds and composition. `out/contact_sheet.jpg` was visually
reviewed: local titles are legible, gameplay and reaction remain visible in all
formats. Titles are `NO SHOT` and `SKILL ISSUE`; no model-written title is used.

The demo source intervals are fixed, bounded examples (Valorant 2-10 seconds;
Deadlock 120-128 seconds), ranked by the existing sharpness/motion heuristic.
Production exports select from their highest-scoring included highlight. Reaction
selection samples four frames from a named expressive clip, using motion as a
cheap proxy; no semantic face-expression analysis is claimed.

## Commands executed

From this worktree root, using the installed Git Bash and configured Linux runner:

```sh
bash tools/remote_run.sh 'cd full_app && python -m pytest -q tests/test_social.py tests/test_thumb.py'
# Initial implementation: 55 passed, remote exit=0.

bash tools/remote_run.sh 'python -m py_compile demo_video/thumb/live_smoke.py && cd full_app && python -m pytest -q tests/test_fix4.py tests/test_social.py tests/test_thumb.py tests/test_int02.py tests/test_publish.py'
# Regression check before composition refinement: 121 passed, remote exit=0.

bash tools/remote_run.sh 'python -m py_compile demo_video/thumb/live_smoke.py && cd full_app && python -m pytest -q tests/test_thumb.py tests/test_social.py'
# Composition refinement: 58 passed, remote exit=0.

bash tools/remote_run.sh 'python demo_video/thumb/live_smoke.py --compose-only && cd full_app && python -m pytest -q tests/test_fix4.py tests/test_social.py tests/test_thumb.py tests/test_int02.py tests/test_publish.py'
# Offline recomposition plus broader regressions: 124 passed, remote exit=0.

bash tools/remote_run.sh 'cd full_app && python -m pytest -q tests/test_thumb.py tests/test_fix4.py'
# Final shared legacy/share-kit image-budget fix: 32 passed, remote exit=0.
```

Explicit live commands (not pytest):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File demo_video/thumb/run_live.ps1
# Exit 1: preview unavailable, Valorant generated, Deadlock quota fallback.
powershell -NoProfile -ExecutionPolicy Bypass -File demo_video/thumb/run_live.ps1 -RetryFailed
# Exit 0: two Deadlock candidates generated; aggregate attempts=7.
```

No credentials, source videos, or generated binary assets are committed.
The launcher reads the external `.env` only at runtime and passes the key through
SSH stdin. It never copies that file or key into the worktree or command arguments.

## Integrator and remaining risks

See [the exact integration handoff](../../docs/social.md#thumb-1-integration-handoff-outside-this-tasks-allowed-paths).
The Full experience preset is `full_app/pipeline/experience.py:7`; its UI button
is `full_app/production_frontend/src/components/EditSettings.tsx:32`. Both need
`gemini_image=True`/`"gemini_image"` respectively, plus the option declaration,
validation/capability plumbing and `build(..., client=image_client, job=job)`
call described there. These files are outside this task's allowed paths.
Until integration, the existing pipeline caller still creates local thumbnails
and only the metadata receives its warnings; callers passing `job=job_state`
get the required job-level warnings as well.

Generated scenes can stylize or invent visual details; both candidates are offered
for human review. Quota failures remain possible and visibly fall back. The team
pack must exist on the deployment host to include a reaction. No image model is
called unless explicitly enabled with a supplied client.
