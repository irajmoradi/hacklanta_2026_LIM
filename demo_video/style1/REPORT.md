# STYLE-1 result

Branch: `ext/STYLE-1`. Implementation commit: `14b372e` (`Respect edit styles
in stacks and preserve gameplay under damage and banners`). Replay/QA scripts
and this report are the following milestone commit. No push or merge.

Implemented the style policies and readability changes within the task allowlist.
All four requested saved-analysis renders are delivered. **Full-suite green is
not achieved:** four assertions in two out-of-scope test files encode the old
style-insensitive behavior. They need owner updates described below. No tests
were skipped, marked xfail, or modified to conceal these failures.

## Changes and choices

* `full_app/planner/stacks_style.py`: Clean/Cinematic budgets, sustained grades,
  sparse neutral climax title, removal of inherited editorial captions/reactions,
  cinematic fades and quiet-to-loud SFX. Clean uses only one/two quiet sounds
  for the entire montage. Restacks receive the same policy as fresh plans.
* `full_app/planner/stacks.py`: restrained-style dispatch, clip-label-aware Meme
  eligibility and fail grades, higher Meme sound density, louder climax sounds.
  Hype retains the FX-3 bold build/hit/aftermath stacks and seeded choices.
* `full_app/fx/bold.py`: damage centre tint reduced to 10% for 0.4 seconds with
  translucent red edge bands; banners restricted to a 22%-height band with
  contained text. Opaque YUV working format avoids alpha compositing surprises.
* `full_app/tests/test_style_stacks.py`, `test_style_readability.py`: style/mode/
  chaos matrix, determinism, restacks, short/empty plans, allowed sets and counts,
  actual FFmpeg centre-contrast and banner-height checks in both orientations.
  Existing FX-3 tests exercise every bold effect's visible pixels and gating.
* `docs/fx.md`: policies, exceptions, replay commands and integration boundaries.
* `demo_video/style1/render_demo.py`, `verify.py`, `fetch.sh`: offline saved-analysis
  replay, decoded export QA, per-style/combined hit contact sheets, local fetch.

Reasonable choices: style does not change source selection or override nice/mean;
Clean gets one neutral title instead of copying long source descriptions;
Cinematic grades tense/build clips cold and a winning climax warm. Atmosphere
intentionally repeats across cuts instead of following the bold-stack repeat
caps. A single-clip cinematic montage is also its climax and can have a sound.

## Commands and actual results

All commands ran from this worktree root on runner 1 through the required wrapper.

```bash
bash tools/remote_run.sh 'cd full_app && python -m pytest -q tests/test_planner_stacks.py tests/test_vfx_bold.py'
# exit 0: 62 passed in 12.81s

bash tools/remote_run.sh 'cd full_app && python -m pytest -q tests/test_style_stacks.py tests/test_style_readability.py'
# Initial exit 1: 2 failed, 39 passed. Overlapping 16% damage tints lost too much
# decoded contrast; reduced each tint to 10% before the successful run below.

bash tools/remote_run.sh 'cd full_app && python -m pytest -q tests/test_style_stacks.py tests/test_style_readability.py tests/test_planner_stacks.py tests/test_vfx_bold.py tests/test_render_stacks.py'
# exit 0: 185 passed in 27.14s

bash tools/remote_run.sh 'cd full_app && python -m pytest -q'
# exit 1: 4 failed, 1280 passed, 20 skipped in 675.02s

bash tools/remote_run.sh 'python demo_video/style1/render_demo.py && python demo_video/style1/verify.py'
# All four renders completed. Initial verification exit 1: cinematic master AAC
# decoded peak 1.011113. Added audio-only export headroom repair, preserving video.

bash tools/remote_run.sh 'python demo_video/style1/render_demo.py --finalize-existing && python demo_video/style1/verify.py'
# exit 0: all eight master/Discord files decode, durations match, peaks <1,
# every Discord copy <20,000,000 bytes; all contact sheets generated.

bash demo_video/style1/fetch.sh
# exit 0: final artifacts copied to ignored local demo_video/style1/out/.

git diff --check
# exit 0
```

Final full-suite failures (the requested style change invalidates old assertions):

| Test | Old assertion | Required owner update |
|---|---|---|
| `tests/test_planner.py::test_effects_speed_peak_trims_and_styles[clean edit]` | 2-5 SFX on the climax | Assert 1-2 tasteful SFX **total**, no reactions, sparse title. |
| Same test `[cinematic]` | At most four named effects, including slow-motion annotation | Permit sustained vignette/dark mood/grain + grade and optional speed annotation; cinematic sound/energy/text policy. |
| `tests/test_planner_adapter.py::test_native_planner_to_real_pipeline[clean edit]` | `reactions_1` must render | Assert no reaction stage for Clean. Video/audio/duration assertions already passed. |
| Same test `[cinematic]` | `reactions_1` must render | Assert no reaction stage for Cinematic. Video/audio/duration assertions already passed. |

These paths are excluded from STYLE-1's `allowed_paths`; they were left untouched.
The new allowed-path acceptance tests cover their replacement style contracts.

## Delivered exports

Runner directory: `/srv/demo_out/style1/`. Local: `demo_video/style1/out/` (ignored).
Masters are H.264/AAC, 30 FPS, 1080p landscape or 1080x1920 vertical. All durations
are within 0.034 seconds of their requested budget. No pipeline warnings.

| Export | Requested duration | Planned clips / VFX / SFX | Discord bytes | Master / Discord decoded peak |
|---|---:|---|---:|---|
| `montage_mean_vertical` (Meme) | 30s | 5 / 24 / 25 | 8,775,520 | 0.88451 / 0.99497 |
| `montage_landscape` (Hype) | 60s | 7 / 28 / 29 | 17,655,224 | 0.96980 / 0.96149 |
| `montage_cinematic` | 30s | 4 / 18 / 2 | 8,897,145 | 0.92348 / 0.98523 |
| `montage_clean` | 30s | 4 / 4 / 2 | 8,893,988 | 0.81235 / 0.98885 |

`manifest.json` records source-plan/output hashes, stream metadata, times, zero
live calls and privacy=false. `verification.json` records final hashes and measured
peaks/durations. `effects.md` lists per-clip effect clocks and sounds.
`contact_sheet.jpg` and `contact_sheet_{mean_vertical,landscape,cinematic,clean}.jpg`
show actual hit and +0.3s aftermath frames. All four per-style sheets were visually
inspected; a full-resolution first Meme hit was also checked with damage and
banner simultaneously active. Gameplay remains visible; banners stay in their
band. Cinematic is deliberately dark; Clean retains unembellished gameplay.

Privacy, cards, reactions, captions and music are disabled for these isolated
style demos. The caption toggle currently also gates editorial titles, so the
one-title Clean/Cinematic plans do not burn that title into these demo exports.

## How to try / remaining integration risks

Play any local `out/montage_*_discord.mp4`, inspect the contact sheets, or rerun
the replay/verify/fetch commands above. For plans, call `planner.plan_edit` with
`style='clean edit'`, `'cinematic'`, `'meme edit'` or `'hype montage'`, plus mode,
chaos and seed. No provider calls are needed. New demo runs automatically apply
decoded audio headroom repair; `--finalize-existing` resumes export QA only.

* Full-suite green still requires the four out-of-scope assertion updates above.
* Music energy is intent metadata: its adapter/render mapping is outside this task.
* Optional post-stack effect refinement is outside this policy stage. Its owner
  should enforce style eligibility before enabling it for restrained styles.
* Core nice/mean clip proportions, caption-toggle semantics and manual custom
  plan behavior remain owned by other tasks. This work does not alter those APIs.
* Cinematic export needed audio-only AAC headroom repair; the generic pipeline's
  post-encode audio policy is unchanged. Video streams were preserved.

Zero live calls. The key file was not read, copied or used. Media stays ignored;
only source, tests, documentation and replay scripts are committed.
