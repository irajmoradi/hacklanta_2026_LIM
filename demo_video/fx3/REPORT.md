# FX-3: bold visual montage effects

Branch: `ext/FX-3`. No push, merge, key-file read or live API call.

## Implementation

- `79f492a`: 40 bold catalog choices (39 new IDs plus upgraded timed freeze),
  phase-aware seeded stacks, kill confirmations and visibility regression tests.
- `abf5a95`: original precomputed skull/flame/laughter/confetti PNG sprites and docs.
- `f115a8d`: reproducible network-blocked demo rendering and verification scripts.
- `2998111`: visual QA correction: freeze footage before compositing animated hit
  effects, plus a regression test.
- The final documentation commit contains this report, artifact fetch helper and
  per-clip effects table.

The chooser now guarantees at least three bold VFX per clip. Subtle grades never
fill these slots. Normal-speed clips receive four layers: a build-up, two hit
layers and aftermath. Slow-motion clips receive three bold layers plus their
existing speed annotation, with hit and aftermath overlapping. Decorative
durations are .7–1.2s; additional explicit-kill confirmations are .4s. Windows
move earlier at clip boundaries instead of shrinking to a few frames. Existing
very short clips use their full duration if .35s is physically impossible.

All visuals use the existing one-graph-per-segment path. PNGs total 36,358 bytes
and are generated with `python full_app/fx/sprites.py`; no artwork, font or ML
download is required. Skull, fire and laughter are original drawings. Glitch,
radial trail and flare are inexpensive stylizations, not optical flow or actual
bitstream corruption. The freeze pointer marks center/crosshair, not a detected
enemy. Deterministic seed and chaos choices are retained.

## Saved-analysis demos

Run from the worktree root:

```bash
tools/remote_run.sh "cd full_app && python ../demo_video/fx3/render_demo.py && python ../demo_video/fx3/verify.py"
```

Inputs are saved DEMO-02 jobs and their existing source on runner 1. The saved
mean vertical plan is 20s, so the demo replans its reviewed keep-list locally to
30s; it does not re-analyze footage. Landscape preserves the saved 60s cuts and
switches decoration to mean mode. Both use seed 2026, chaos .8, privacy off,
captions off and reaction packs off. The demo explicitly blocks Python network
connections. Outputs are `/srv/demo_out/fx3/` and local `out/` (gitignored).

Final rerender plus verification completed with exit 0 after the freeze-order
fix. Plans, manifest, per-clip effects, contact sheet and full-size hit/aftermath
frames are retained alongside the videos. Copy final files locally with
`bash demo_video/fx3/fetch.sh`; this excludes intermediate render directories.

| Mean montage | Master | Discord | Duration | Final render + Discord time |
|---|---|---|---|---|
| Vertical | [22.23 MB](out/montage_mean_vertical.mp4) | [8.84 MB](out/montage_mean_vertical_discord.mp4) | 30.031s | 95.87s |
| Landscape | [68.08 MB](out/montage_landscape.mp4) | [17.69 MB](out/montage_landscape_discord.mp4) | 60.031s | 125.61s |

All four files decode fully; decoded float audio peaks are below full scale
(vertical master .8901 / Discord .8165; landscape master .9388 / Discord .8665).
All local video SHA-256 values match `out/verification.json` from the runner.
Timings include Discord conversion and concurrent runner load, not isolated
filter benchmarks. Both jobs returned zero warnings. Outputs and QA images are
gitignored; only code, original small sprites, docs and the per-clip table are
committed.

I visually inspected the [contact sheet](out/contact_sheet.jpg), the full-size
vertical opening hit and the corrected landscape freeze hit. Large banners,
colored X bursts, chunky RGB displacement, speed streaks and original sprite
rain remain obvious at contact-sheet/phone size. Text stays within frame bounds.
The first contact sheet exposed a freeze compositing issue: freezing a pre-hit
composite hid downstream hits. Commit `2998111` puts freeze first; the rerendered
[freeze hit](out/landscape_1_hit.png) now visibly combines its outline/pointer,
hitmarker and RGB split. See [effects.md](effects.md) for every clip's source,
peak, VFX placement/duration and SFX stack.

## Test execution

Every command below ran through `bash tools/remote_run.sh` from the worktree
root, with the listed inner command. No local-only test results are substituted.

| Inner command (`cd full_app && ...`) | Result |
|---|---|
| `python -m pytest -q tests/test_render_stacks.py tests/test_planner_stacks.py` | Exit 1: 88 passed, 5 failed. Initial extra kill-confirmation layer exceeded old four-layer checks; fixed by reserving a hit slot. |
| `python -m pytest -q tests/test_render_stacks.py tests/test_planner_stacks.py tests/test_planner.py tests/test_fx.py` | Exit 1: 182 passed, 3 failed. Secondary hit choices consumed the marker inventory; fixed by reserving markers for the primary hit slot. |
| `python -m pytest -q tests/test_planner_stacks.py tests/test_planner.py tests/test_vfx_bold.py` | Exit 1: 101 passed, 1 failed. New explicit-kill fixture omitted required `label`; fixture corrected. |
| `python -m pytest -q tests/test_vfx_bold.py tests/test_planner_stacks.py tests/test_render_stacks.py tests/test_planner.py && python ../demo_video/fx3/render_demo.py` | Exit 0: 184 passed, then both initial demos rendered. |
| `python -m pytest -q tests/test_vfx_bold.py tests/test_render_stacks.py` | Exit 0: 130 passed with final PNG sprites, followed by the full-suite command in the same remote session. |
| `python -m pytest -q --junitxml=../demo_video/fx3/out/full-suite.xml` | Exit 0: 1,219 passed, 20 skipped in 726.18s before the freeze-order correction. |
| `python -m pytest -q tests/test_vfx_bold.py tests/test_planner_stacks.py tests/test_render_stacks.py tests/test_planner.py` | Exit 0: 185 passed in 32.71s with the freeze-order correction. |
| `python ../demo_video/fx3/render_demo.py && python ../demo_video/fx3/verify.py` | Exit 0 on final code: both masters and Discord copies rendered, fully decoded and checked; final contact sheet generated. This followed the 185-test command in the same remote session. |
| `python -m pytest -q --junitxml=/srv/demo_out/fx3/full-suite-final.xml` | **Exit 0 on final code: 1,220 passed, 20 skipped in 624.57s.** |

The new pixel tests execute all 40 bold effects on synthetic `testsrc2` footage,
check visible changes during placement and unchanged frames outside placement.
Planner tests cover nice/mean, chaos 0/.6/1, events near cuts, minimum durations,
three bold choices, all phases, simultaneous hit layers and every explicit kill.
Existing registry tests execute every legacy and new timed effect at a late
timestamp. No paid smoke test was run.

## Files changed

- `full_app/models/effects.py`: register bold IDs and build cached sprite graphs.
- `full_app/fx/{bold,catalog,sprites,__init__}.py`: original effects, tags, sprite
  generation and timed freeze annotation.
- `full_app/assets/vfx/*.png`: four original transparent sprite canvases.
- `full_app/planner/stacks.py`: phased selection, minimum visibility and explicit
  kill confirmations.
- `full_app/tests/test_vfx_bold.py`: catalog, timing, phases, per-kill and real
  FFmpeg pixel/gating coverage.
- `docs/fx.md`: behavior, tradeoffs, reproduction and timing semantics.
- `demo_video/fx3/`: offline render/verification scripts, ignore rule and report.

## Limits

Saved window descriptions classify reviewed peaks; they do not establish exact
kill coordinates or new timestamps. Additional explicit-kill confirmations may
repeat an ID beyond decorative caps. If a phase inventory is exhausted on a
long montage, visibility takes precedence over repeat caps. Legacy saved plans
retain their original effect timing. Optional external refinement lives outside
this task's allowed paths and can still replace a bold slot with an older
registry effect; no refinement is enabled in these demos. Existing optional
center captions/reactions can overlap VFX when enabled. No shared FINAL-1
renderer/planner files were modified.
