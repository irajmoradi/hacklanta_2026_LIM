---
id: QA-1
branch: ext/QA-1
allowed_paths: [full_app/reactions/**, full_app/sam/**, full_app/fx/**, full_app/narration/**, full_app/privacy/**, full_app/music/**, full_app/multipov/**, full_app/tests/test_reactions*.py, full_app/tests/test_sam*.py, full_app/tests/test_fx*.py, full_app/tests/test_narration*.py, full_app/tests/test_privacy*.py, full_app/tests/test_music*.py, full_app/tests/test_multipov*.py, docs/reactions.md, docs/sam.md, docs/fx.md, docs/narration.md, docs/privacy.md, docs/music.md, docs/multipov.md]
---
# QA-1: Quality pass: media feature modules
**Goal: reduce slop.** The Extension was written fast by many AI agents. Make the code something a senior engineer would be happy to maintain:
- Delete dead code, unused functions/params/imports, duplicate helpers (consolidate into one shared helper), copy-pasted ffmpeg/probe/subprocess
  wrappers (reuse `services/ffmpeg_runner.py` / `services/probe.py` or one small shared util), speculative abstractions with a single implementation,
  config knobs nobody reads, and over-long try/except that hides errors.
- Make names, return types, error handling and logging consistent across modules; add type hints where missing; keep functions small.
- Comments and docstrings: short, factual, explain *why*; remove filler, marketing tone, restated code, emoji, and AI-isms ("robust", "seamlessly",
  "leverage", "comprehensive", "it's worth noting"). Same for the module docs you own.
- Tests: remove redundant/near-duplicate tests, keep coverage of real behavior; no sleeping/flaky tests; make slow tests marked.
- Do not change public behavior or APIs other modules use (grep for callers first). No new features.
Run the full suite on the runner before and after (`tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"`): no new failures
(some may already fail on `Extension` while integration is in progress; report before/after counts). Report lines removed vs added per module.
