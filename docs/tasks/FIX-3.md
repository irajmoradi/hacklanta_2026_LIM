---
id: FIX-3
branch: ext/FIX-3
allowed_paths: [full_app/demo/**, full_app/eval/**, full_app/tests/e2e/**, full_app/tests/test_eval*.py, docs/e2e.md, docs/eval.md, docs/results.md]
---
# FIX-3: Apply QA-3 demo/eval items: real adapters and live budget
Read `docs/quality_report.md` (QA-3 audit of `Extension`) first; it gives file:line evidence and the exact fix for each item. Apply the items
assigned to you, verify each by reading callers, add/adjust tests, and keep the **whole** suite green on the runner
(`tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"`; it is currently 907 passed / 0 failed). Do not touch files outside your
paths; if an item needs a change elsewhere, describe it in your report. Mark each item fixed / partially / not in your report.
Your items: **P1-03** (repair the demo/E2E adapter to exercise `create_app` and `JobStore` instead of removed globals; `full_app/demo/run_demo.sh` must produce a real montage end to end on the runner), **P1-07** and **P1-08** (fix the real evaluation adapters; enforce the live-call budget at the generation boundary), plus any P2/P3 items in the report that live only in your paths. Then rerun EVAL-02's benchmark and update docs/results.md if numbers change.
