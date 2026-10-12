---
id: FIX-1
branch: ext/FIX-1
allowed_paths: [full_app/app.py, full_app/server/**, Dockerfile, docker-compose.yml, full_app/tests/test_jobs*.py, full_app/tests/test_security*.py, full_app/tests/test_server*.py, docs/api.md, docs/security.md]
---
# FIX-1: Apply QA-3 server items: exposure/auth, SSE starvation, plan admission, resource bounds
Read `docs/quality_report.md` (QA-3 audit of `Extension`) first; it gives file:line evidence and the exact fix for each item. Apply the items
assigned to you, verify each by reading callers, add/adjust tests, and keep the **whole** suite green on the runner
(`tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"`; it is currently 907 passed / 0 failed). Do not touch files outside your
paths; if an item needs a change elsewhere, describe it in your report. Mark each item fixed / partially / not in your report.
Your items: **P1-01** (bind local defaults to 127.0.0.1 incl. Compose host port; optional token auth + job ownership checks on all job/media/action routes when not local), **P1-02** (SSE must not starve the worker threads: close terminal/idle streams, heartbeat with a max lifetime, and a server config that supports concurrent streams), **P1-06** (one typed plan boundary before queue admission; enforce source/effect/duration limits), **P1-10** (bound media subprocess time/memory and upload/storage usage), plus any P2/P3 items in the report that live only in your paths.
