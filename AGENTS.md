# AI Gameplay Clip Editor: Extension sprint rules (every coding agent)

Repo: `irajmoradi/hacklanta_2026_LIM`. All work happens on the **`Extension`** branch (never `main`). Each task runs on its
own branch `ext/<TASK>` in its own git worktree; the integrator merges into `Extension`.

App today: `full_app/app.py` (Flask) uploads gameplay → `services/gemini_client.py` asks Gemini for highlight/lowlight clips
(`prompts/clip_finder.txt`) → Gemini plans an edit (`prompts/editor.txt`) → `services/ffmpeg_runner.py` renders a montage with
effects (`models/effects.py`) and meme SFX (`sfx/`). Frontends: `full_app/frontend/` (simple) and
`full_app/production_frontend/` (React + Vite + Tailwind).

## Rules
- Stay inside your task's `allowed_paths`. Keep the app working end to end (upload → analyze → plan → render) at every commit.
- New modules go in `full_app/` with clear names; keep old behavior behind defaults unless the task says to replace it.
- **No secrets** in git. Keys come from env (`GEMINI_API_KEY`, optional others). Never commit `.env`, videos, model weights.
- **Paid API calls only in explicitly marked live smoke tests, ≤ 3 calls per task run.** All unit/integration tests mock Gemini.
- Heavy/optional ML deps (whisper, ocr, torch) must be **optional extras** with graceful fallback when missing.
- Write tests (pytest; vitest for the frontend). Run them on the Linux runner (it has ffmpeg):
  `tools/remote_run.sh <command>` from your worktree root (e.g. `tools/remote_run.sh "cd full_app && python -m pytest -q"`).
  Generate synthetic test videos with ffmpeg (`testsrc2`, `sine`, `drawtext`) inside tests; never download copyrighted media.
- Report real commands and exit codes. Never claim a test passed that you did not run.
- Commit small on your branch. Never push, never force-push, never merge.

## Final report (every task)
Branch + commits, files changed, test commands + results, how to try it, what's left / risks.
