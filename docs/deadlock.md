# Deadlock real-footage calibration (DEADLOCK-1)

Branch: `ext/DEADLOCK-1`. Implementation milestone: `35ff180`.
Reproduction/live harness milestone: `a362ed3`. No push or merge performed.

Changed files (all within the task allowlist):

```text
full_app/profiles/data/deadlock.json
full_app/profiles/deadlock_hud.py
full_app/profiles/detection.py
full_app/profiles/hud.py
full_app/signals/detector.py
full_app/signals/ocr.py
full_app/privacy/profiles.py
full_app/prompts/games/deadlock.txt
full_app/tests/test_deadlock.py
demo_video/deadlock/.gitignore
demo_video/deadlock/measure.py
demo_video/deadlock/launch_live.py
demo_video/deadlock/live_smoke.py
docs/game_profiles.md
docs/deadlock.md
```

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
`/render`, `ingest=true`, privacy off, local planner and the runner's team reaction pack. It
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

Final full suite: **1,072 passed, 20 skipped**, 639.20 s, exit 0, using:

```sh
bash tools/remote_run.sh 'set -o pipefail; cd full_app && OMP_THREAD_LIMIT=1 python -m pytest -q 2>&1 | tee /srv/demo_out/deadlock/pytest-full.log'
```

The initial direct-source live run exited 1 during `whole_video`: the stock
600-second 1080p60 chunk encoding reached the provider's 300-second processing
timeout. It had spent 12 window-scoring calls. The harness now enables the
existing stock ingest path (normalized media plus analysis proxy/chunks), then
retries the same job without resetting its ledger. The uploaded original remains
the render source. No provider or pipeline files were modified. The failure
snapshot is preserved as `previous-error-status.json`.

Full-source scans both exited 0, with uninterrupted OCR:

| Measurement | Auto game / confidence | Feed candidates | Souls-gain candidates | Scene cuts | Total time |
| --- | --- | ---: | ---: | ---: | ---: |
| Original full-frame OCR + generic keyword parser | generic / 0.000 | 0 | 0 | 30 | 431.85 s |
| Updated HUD + row parser | deadlock / 0.781 | 19 | 74 | 30 | 437.71 s |

Updated detection itself took 35.88 s (16 sampled frames). Both scans covered
all 1,113.683 seconds. Neither scan detected a death or explicit objective
destruction. This does **not** establish that the recording contains none.
The 19 feed candidates include other players and assists, and several adjacent
timestamps may be duplicate OCR identities. The 74 economy candidates are weak
proposals and can include numeric OCR errors. These are not recall/precision
scores or verified event totals. Timing reflects shared runner load.

Manually inspected source frames (file timestamps, not the HUD match clock):

| File time | Visible evidence | Attribution limit |
| --- | --- | --- |
| 225 s / 03:45 | Upper-left elimination row and centre KILL ASSIST badge | An assist, not proof of a recorder kill |
| 945 s / 15:45 | Upper-left elimination row while the recorder uses a zipline | Global teammate event; recorder attribution unknown |
| 1,025 s / 17:05 | Upper-left elimination row, centre KILL badge and 7 KILL STREAK | Recorder elimination corroborated by the badge |

The HUD match clock is nine seconds ahead of the file clock in these inspected
frames. Measurements and exported clip source ranges use file seconds.

Remaining validation results and artifact sizes are recorded below after the
full scan, full suite, and live smoke complete.

## Limits

Calibration covers this recording's HUD, not every Deadlock patch, language,
colorblind palette, aspect ratio, player name alphabet or UI scale. Color/shape
cues can be occluded by shops and menus. Sampling can miss brief feeds; OCR can
duplicate or miss names. Objective and souls signals require downstream video
verification. No trained model, heavy dependency, weight download or new service
is introduced. Other sprint agents' paths are not modified.
