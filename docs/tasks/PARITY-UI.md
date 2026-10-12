---
id: PARITY-UI
branch: ext/PARITY-UI
allowed_paths: [full_app/server/**, full_app/app.py, full_app/pipeline/orchestrator.py, full_app/pipeline/extensions.py, full_app/pipeline/demo.py, full_app/planner/planner.py, full_app/planner/models.py, full_app/planner/adapter.py, full_app/production_frontend/**, full_app/tests/test_jobs*.py, full_app/tests/test_server*.py, full_app/tests/test_parity*.py, full_app/tests/test_pipeline*.py, full_app/tests/test_planner.py, full_app/tests/test_social*.py, docs/api.md, docs/pipeline.md, docs/frontend.md]
---
# PARITY-UI: Restore original UI/API features + wire Nano Banana thumbnails

Apply item 3 of the prioritized list in `docs/parity_audit.md` (PARITY-1) and the THUMB-1 integrator handoff in `docs/social.md`
("These changes belong to the integrator"). In particular:
1. **UI controls lost vs the original app** (`main:full_app/frontend/index.html`): max duration (10-600 s, sensible defaults per preset),
   free-text **analysis instructions** (must reach analysis; do not overwrite with "Game: … Profile: …", append instead), free-text
   **editing instructions** (reach planner v2: feed them to the Gemini plan refinement when enabled, and to the Director/editor agent as its
   first instruction otherwise; document), mean mode auto-selects **Meme Edit** and nice selects **Hype Montage** unless the user picked a
   style, **nice ≈70% highlights/30% fails and mean ≈70% fails/30% highlights** in planner v2 selection, a **Job log** panel (server already
   keeps logs), a **raw plan JSON** view with import/export (validated through the typed plan boundary), and the source **metadata grid**
   (filename, size, duration, resolution, fps, codecs) after upload.
2. **THUMB-1 wiring:** `gemini_image` in Full experience, UI toggle "AI thumbnails", validation `EXTENSION_FLAGS`, capabilities advertising,
   and construct/close the image client in `pipeline/extensions.py` with the job's call budget; show both thumbnail candidates in the share kit
   view. `pipeline/experience.py` is owned by FISH-1 (running): put the one-line `gemini_image=True` preset change in your report instead.
3. Contract tests (API ↔ UI options), vitest for new controls, Playwright screenshots of the settings panel, job log and plan JSON view.
   Full suite + frontend build/tests green on the runner. Zero paid calls in tests.
SAMFIX-1 (sam/reactions), STYLE-1 (effects/stacks) and FISH-1 (cards, experience.py, rendering.py) are running: stay inside your paths.
