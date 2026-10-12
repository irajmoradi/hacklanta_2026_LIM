# Deadlock real-footage calibration (DEADLOCK-1)

Branch: `ext/DEADLOCK-1`. Implementation milestone: `35ff180`.

The source is `/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4`, a 1,113.683-second
1080p60 VP9 recording supplied on runner 1. Its adjacent attribution file identifies
**No Copyright Gameplay**, [source video](https://www.youtube.com/watch?v=aXZYyd4SoWM),
Creative Commons Attribution (CC BY). No source footage is committed or downloaded
from a third party by this task. Distributed montage copies burn in
`Gameplay: No Copyright Gameplay (CC BY)`; raw stock API outputs retain the
separate attribution here and in the output folder.

## Detection and events

The inspected HUD has an **upper-left** cream/red elimination feed, health left
of centre, mint souls at bottom left, a four-lane minimap at bottom right, a top
portrait/team-souls bar and bottom-centre abilities. The old upper-right feed
crop was incorrect for this recording. Shared profile and privacy coordinates
now agree with the signal reader. The broad right-side death-report region is
retained for keyword detection; the event reader looks for a lower-centre respawn
banner.

Auto detection adds a bounded fallback requiring timer OCR, mint numeric souls
or the word SOULS, all four map lane colors, and distributed top portrait colors
together in at least three frames and 18% of decoded samples. It only resolves
an otherwise generic result. Injected OCR hooks preserve their full-frame-only
contract. Confidence is heuristic support, not a calibrated probability. The
numeric/mint alternative handles small SOULS glyphs that Tesseract misreads.

Feed parsing locates aligned cream/red bars, bridges text-sized gaps, enlarges
each row, and OCRs both dark and light text. It requires two name-like tokens and
deduplicates identities across row movement and OCR jitter. Participant names
in regression fixtures are invented ALPHA/BRAVO/CHARLIE tokens. Report artifacts
persist only event types and timestamps. Feed events carry unknown attribution:
they are not a verified player kill tally.

Explicit destruction/delivery phrases produce objective candidates. A persistent
ENEMY WALKER or FRIENDLY GUARDIAN health bar does not. A short-interval souls
increase of 300–5,000 produces weak `souls_gain` evidence (one quarter of a kill's
OCR contribution); purchases, long sampling gaps, and small farming increments
do not. OCR errors can still mimic a gain. Ultimate use and orb denies require
video verification and are not inferred from icons or numeric changes.

Deadlock alone applies the profile's motion/OCR multipliers to local fusion,
respecting explicit caller weight overrides, with additional objective weighting.
The scoring fragment favors consequential picks, fights, multikills, objectives,
escapes and verified denies; mean mode requires an observable mistake and outcome.

## Reproduction

From the worktree root (Git Bash on Windows):

```sh
bash tools/remote_run.sh 'OMP_THREAD_LIMIT=1 PYTHONPATH=full_app python demo_video/deadlock/measure.py /srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4 --baseline'
bash tools/remote_run.sh 'OMP_THREAD_LIMIT=1 PYTHONPATH=full_app python demo_video/deadlock/measure.py /srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4'
bash tools/remote_run.sh 'cd full_app && OMP_THREAD_LIMIT=1 python -m pytest -q tests/test_deadlock.py tests/test_game_profiles.py tests/test_fix5.py tests/test_signals.py'
bash tools/remote_run.sh 'cd full_app && OMP_THREAD_LIMIT=1 python -m pytest -q'
```

Measurements scan the full stream at 2 fps with 960-pixel OCR frames every two
seconds. Missing/failed Tesseract is an error in the measurement harness, while
the application retains graceful fallback. Baseline injects the old full-frame
reader and selects the unchanged generic keyword parser on this source.

The explicitly authorized live smoke is `python demo_video/deadlock/launch_live.py`
on Windows, **after syncing with the runner**. It reads GOOGLE_API_KEY at runtime
from the user-specified `.env`, sends it over SSH stdin, and configures Vertex
express. It never writes credentials. The single resumable job has a durable
50-attempt cap, SDK retries disabled, one application attempt, 12 top candidate
windows and no VLM game-detection call. Ordinary tests block provider access.

The smoke uses stock `POST /api/jobs`, `/analyze` with `game=auto`, `/plan`, and
`/render`, privacy off, local planner and the runner's team reaction pack. It
copies `/srv/packs/team` into the runner worktree only. **Do not resync while the
live render is using that runner-only pack**: the helper's `rsync --delete` would
remove it. The launcher recopies it on a resumed run. It reuses the marker and
budget ledger under `/srv/demo_out/deadlock`, never creates a fresh job to reset
the call budget, and resumes completed analysis.

Outputs, status snapshots, counts and timings live in `/srv/demo_out/deadlock/`.
Local copies belong under gitignored `demo_video/deadlock/out/`. Nice landscape
targets 45 seconds; mean vertical targets 30. Credited exports and separate
Discord encodes are produced after the stock renderer. Discord copies must be
less than 20,000,000 bytes and credited outputs must decode without errors.

## Validation record

Focused runner suite: **90 passed, 2 skipped**, 47.34 s, exit 0. Includes real
Tesseract at 1920/1280/960 widths, full synthetic-video sampling, competing
Valorant/OW2/League fixtures, persistence/multikill identity, missing OCR, objective
phrases and economy changes. Skips are not claimed as passes.

Initial full-suite invocation failed before pytest because of Windows shell
quoting (remote exit 2; local exit 1). The corrected invocation uses
`set -o pipefail` with `tee` to preserve pytest's exit code.

Full-source baseline: generic / 0.000, zero OCR events, 30 scene cuts, 431.85 s,
exit 0. Updated auto detection: deadlock / 0.781 (16 sampled frames).

Remaining validation results and artifact sizes are recorded below after the
full scan, full suite, and live smoke complete.

## Limits

Calibration covers this recording's HUD, not every Deadlock patch, language,
colorblind palette, aspect ratio, player name alphabet or UI scale. Color/shape
cues can be occluded by shops and menus. Sampling can miss brief feeds; OCR can
duplicate or miss names. Objective and souls signals require downstream video
verification. No trained model, heavy dependency, weight download or new service
is introduced. Other sprint agents' paths are not modified.
