# FINAL-2 combined render

Branch: `ext/FINAL-2`. No push or merge.

The earlier offline FINAL-1 replay remains documented in
`demo_video/final/REPORT.md` and its `render_saved.py` / `verify.py` scripts.

## Implementation

`60cb857` removes the full-frame red fill from both damage effects. Only three
translucent edge borders remain; their recommended event duration is 0.4 seconds.
Pixel tests exercise single and stacked damage layers in landscape and portrait,
requiring at least 75% centre contrast. Every bold effect also gets a measured
centre coverage/opacity check, with tighter limits on borders and banners than
on intentional full-frame distortion effects.

The rendering adapter now budgets both cards inside `max_duration`, after legacy
time effects have been prepared and before music, SAM and card generation. It
uses whole-frame allocations, symmetrically trims source ranges, clips local
captions/effects/reactions/sounds/tracks, and retains selected clips where the
budget permits. Transitions and beat sync may shorten the result further. Short
requests shorten cards; requests without an explicit cap retain their defaults.
Narration and share export consume the adjusted source ranges. No provider calls
are introduced by budgeting.

## Reproduction

All scripts below live in `demo_video/final2/`. `prepare.py` and `collect.py` make
no provider calls. `launch.py` is an **explicit paid live smoke test**. It reads
only `GOOGLE_API_KEY` from the authorized local dotenv at runtime and sends it
over SSH stdin, never saving it. Vertex express is selected with
`GOOGLE_GENAI_USE_VERTEXAI=true`.

1. `bash tools/remote_run.sh "python demo_video/final2/prepare.py"`
2. Install optional CPU Torch/SAM2 and faster-whisper in the runner venv, pinning
   `av==18.0.0` for faster-whisper 1.2.1, then run
   `demo_video/final2/check_runtime.py` there.
3. `python demo_video/final2/launch.py`
4. On runner 1: `.venv/bin/python demo_video/final2/collect.py` from the worktree.

The harness serves the stock jobs API on loopback port 8022 and sends real HTTP
uploads, analyze, plan and render requests. It never edits the job database or
injects analysis/plans. There is no stock analysis-import endpoint, so Valorant
uses a fresh analysis of source 960–1560 seconds: the ten-minute window containing
the most saved DEMO-02 clip starts (28). Deadlock uses the provided CC BY source.

Durable job ceilings sum to 60, including every image attempt. The initial
visual audit spent 19 attempts before the caption/SAM-evidence corrections;
those attempts remain charged. Final allocations are 14 for Valorant nice,
11 for Valorant mean plus Reroll, and 16 for Deadlock nice plus mean. The final
Valorant analyses score four local windows each, while Deadlock scores seven;
all also perform whole-video analysis. Alternate cuts and the changed-seed
Reroll reuse analysis through `/plan`. Separate nice/mean Valorant jobs leave
the stock four-image thumbnail budget sufficient for Reroll. No ledger is reset.
`budget_policy.json`, `jobs.json` and `live_calls.json` preserve the accounting.
Five attempts in Valorant nice were consumed by the stock automatic Director:
nonempty editing instructions invoke it even with no explicit Director flag,
and its independent default ceiling is 12. That run was stopped at 10 total
attempts, then resumed with its existing analysis, blank optional instructions,
`editor_agent=false`, and `EDITOR_AGENT_CALL_BUDGET=0`. Its 14-attempt allocation
includes those five calls plus analysis and the four final card/thumbnail calls.
The hard aggregate ceiling remains 60; no spent calls or ledger rows are erased.

SAM runs locally with `/srv/models/sam2.1_hiera_small.pt`, CPU, four samples per
clip, a 120-second operation timeout and a 300-second clip budget. The team pack
is copied into the runner worktree at launch, because the remote test sync
removes runner-only files. Privacy is off; full experience, FX, performance mode,
captions, reactions, cards, music/beat sync and share kits are enabled.

## Validation so far

- Focused runner command:
  `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_cards_budget.py tests/test_cards.py tests/test_style_readability.py tests/test_wire1.py"`
  — **79 passed, exit 0**. Its initial run had 78 passed / 1 failed, exit 1:
  the six-second narration fixture relied on seven seconds of extra AI cards.
  That fixture now explicitly uses plain cards; separate tests exercise AI cards.
- Runtime preflight: SAM degraded=false, two real model samples in 13.14 seconds;
  Whisper tiny cached; exit 0. This makes zero Gemini calls.
- Full suite and final media audit: results will be recorded below when complete.

The first complete suite returned **1431 passed, 20 skipped, 3 failed**, exit 1,
in 680.37 seconds; all three failures were the PyAV incompatibility below.
A fresh run was intentionally interrupted to include the subsequent audit fixes
(404 passed, 9 skipped, remote exit 2). The audit fixes passed
`bash demo_video/final2/run_checks.sh "cd full_app && python -m pytest -q tests/test_cards_budget.py tests/test_wire1.py"`
with **21 passed, exit 0**. `run_checks.sh` invokes `tools/remote_run.sh`, adding
only an rsync protection rule for runner-only reaction media during live jobs.

The initial video audit found a 67 ms `GG!` footer after trimming. Budgeting now
discards one-word editorial text and phrases shortened below 0.75 seconds; real
speech word captions are unaffected. It also found strict SAM mask rejection
reported as successful application. The adapter now separates accepted masks
from `sam_skipped` records and carries the exact rejection warnings. Synthetic
tests cover both success and rejection. Superseded audit media are kept only
under the runner's `superseded/` folder, not delivered as final masters.

The initial full-suite run exposed an optional-dependency incompatibility:
faster-whisper 1.2.1 passes `metadata_errors` to PyAV; PyAV 19 removed that
argument ([upstream changelog](https://pyav.basswood.io/docs/stable/development/changelog.html)).
The runner venv uses PyAV 18.0.0; default application requirements are unchanged.
Preflight now tests audio decoding as well as model loading.

## Artifacts and attribution

Runner artifacts: `/srv/demo_out/final2/`; local deliverables:
`demo_video/final2/out/` (gitignored). Each cut includes its master, Discord copy
under 20 MB, stock share kit, cards, full job/warnings, stage timings, verification
JSON, and contact sheets sampled at every planned effect/reaction/card.

Deadlock: **Deadlock Gameplay - Free To Use**, by **No Copyright Gameplay**,
<https://www.youtube.com/watch?v=aXZYyd4SoWM>, Creative Commons Attribution
(CC BY), as recorded in the supplied source attribution. Credit is included with
both Deadlock deliverable folders and share kits; retain it when publishing.
