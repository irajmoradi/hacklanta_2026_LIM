---
id: FIX-2
branch: ext/FIX-2
allowed_paths: [full_app/pipeline/**, full_app/render/**, full_app/reactions/**, full_app/planner/**, full_app/services/**, full_app/production_frontend/src/api.ts, full_app/production_frontend/src/**/*.test.*, full_app/tests/test_pipeline*.py, full_app/tests/test_render*.py, full_app/tests/test_reactions*.py, full_app/tests/test_planner*.py, full_app/tests/test_provider*.py, full_app/tests/test_gemini*.py, docs/pipeline.md, docs/rendering.md]
---
# FIX-2: Apply QA-3 pipeline items: settings wiring, captions, square reactions, providers, plan schema
Read `docs/quality_report.md` (QA-3 audit of `Extension`) first; it gives file:line evidence and the exact fix for each item. Apply the items
assigned to you, verify each by reading callers, add/adjust tests, and keep the **whole** suite green on the runner
(`tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"`; it is currently 907 passed / 0 failed). Do not touch files outside your
paths; if an item needs a change elsewhere, describe it in your report. Mark each item fixed / partially / not in your report.
Your items: **P1-04** (send current render settings and map edited captions into the renderer schema; frontend `src/api.ts` mapping included), **P1-05** (square reaction composition + tests for every preset x feature combination), **P1-09** (centralize provider/key selection incl. Vertex express; reject unknown providers), **P2-01** (replace incompatible planner/render schemas with one explicit versioned adapter, tested end to end), plus any P2/P3 items in the report that live only in your paths.
