# FX-2 report

Branch: `ext/FX-2`. No pushes or merges. Live Gemini calls: **0**; no key file was read.

Implementation commits:

- `21c9f31` — seeded tagged stacks, validated chaos/seed contracts, single-call optional refinement, unified mixer and FFmpeg coverage.
- `07c19e8` — saved-evidence restacking, focused impact/roast layers, event anchoring and integration tests.
- `567704f` - final AAC mastering with video stream copy and decoded-peak regression test.
- `c803512` - one word overlay per clip, with non-text roast layers and refinement validation.
- `2fa9491` - boundary-only fades and brief impact flashes, verified after visual QA.
- The documentation/demo commit containing this report records the final artifacts.

## Behavior and scope

Every selected segment receives 1–4 VFX and 2–5 SFX. Consecutive clips do not
reuse decorative IDs, and each ID has a montage cap. Nice gets hype stacks;
mean adds layers, louder sound gains and varied roast text. The catalog contains
42 VFX and 49 SFX, including event/mood/intensity/length tags for every entry.
See [catalog.json](catalog.json) for the complete inventory.

Chaos defaults to .35 nice / .6 mean. Same seed reproduces assignments; a new
seed rerolls decoration without changing cuts. Randomness affects weighted
selection, layer count, timing jitter, gain and occasional wildcard choices.
Explicit signal and kill-feed events retain their source timestamps; saved
window descriptions classify existing reviewed peaks without inventing timestamps.

Both renderer performance modes mix every SFX, with per-sound gain, timed 28%
game-audio ducking, a non-auto-leveling per-segment limiter, and final AAC
mastering with a 0.85 ceiling and video stream copy. Timed text works after two
seconds. Zoom punch, shake, chromatic shift, freeze and deep fry use FFmpeg;
slow motion stays an explicit segment speed with synchronized audio.

**Integration still required outside allowed paths:** `server/validation.py::options_valid`
and `pipeline/extensions.py::planner_plan` do not accept/forward chaos/seed or the complete event
list. Library/service options and render-plan JSON fields are implemented.
The integrator must allowlist/forward these fields and add them to the planning
invalidation keys in `server/queue.py` to expose a working reroll through HTTP.
There is no existing chaos settings field, so UI/Reroll behavior is documented
in `docs/planner.md`. No out-of-scope file was modified.

## Validation

All test commands below use the Linux runner through `tools/remote_run.sh`:

| Command inside runner | Result |
|---|---|
| `cd full_app && python -m pytest -q tests/test_planner.py tests/test_planner_adapter.py tests/test_render_v2.py` | Initial run: exit 1, 69 passed / 5 failed; failures were old fixed-effect/empty-clean-style expectations, subsequently updated for FX-2. |
| `cd full_app && python -m pytest -q tests/test_planner.py tests/test_planner_stacks.py tests/test_render_stacks.py` | Exit 0, 95 passed. |
| `cd full_app && python -m pytest -q tests/test_planner.py tests/test_planner_stacks.py tests/test_render_stacks.py tests/test_planner_adapter.py` | Exit 0, 102 passed. |
| `cd full_app && python -m pytest -q tests/test_planner.py tests/test_planner_stacks.py tests/test_planner_fill.py` | Exit 0, 70 passed on final implementation. |
| `cd full_app && python -m pytest -q` | Exit 0, 1,095 passed / 21 skipped in 855.80 s; first implementation full-suite run. |
| `cd full_app && python -m pytest -q tests/test_render_stacks.py tests/test_render_v2.py tests/test_planner_adapter.py` | Exit 1, 75 passed / 1 failed in the initial mono headroom-test fixture; corrected to loud stereo float PCM, then covered by the successful full suite. |
| `cd full_app && python -m pytest -q --durations=10 --junitxml=../demo_video/fx2/out/full-suite.xml` | **Exit 0, 1,098 passed / 20 skipped in 628.95 s on the final implementation.** |

A decoded sample check found one pre-mastering landscape AAC sample at +0.09 dBFS.
Final mastering was added, and completed renders were mastered without re-encoding
video using `finalize_saved.py`; Discord copies were regenerated. A loud stereo
float-PCM test checks final decoded headroom and unchanged video packet hashes.
The first version of that test incorrectly assumed mono-to-stereo preserved
amplitude (75 passed / 1 failed, exit 1); the corrected stereo clipping fixture
passed individually (exit 0). The final full-suite run includes the corrected test.

The renderer tests execute every timed registry VFX against FFmpeg-generated
`testsrc2` media and render five overlapping SFX through an `amix=inputs=6` graph.
Planner tests cover stacks, adjacency/caps, nice/mean gains, deterministic replay,
reroll, chaos validation, event preservation, mocked one-call refinement and
atomic fallback. Existing pipeline integration tests render synthetic gameplay.

## Verified deliverables

Final saved-analysis render and verification command (exit 0):

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_planner.py tests/test_planner_stacks.py tests/test_planner_fill.py && python ../demo_video/fx2/render_saved.py && python ../demo_video/fx2/verify.py"
```

The command passed all 70 planner tests, rendered all three variants, and verified
full decode, duration, reproducible assignments, sub-20-MB Discord files and decoded
float audio peaks below full scale in every master and Discord copy. Local master
SHA-256 values match the runner manifest. Final QA frames were visually inspected;
event-time fades were removed after an earlier frame review, and roast text no
longer collides with other word effects.

| Montage | Master | Discord | Duration | Master / Discord peak dBFS | Render wall time |
|---|---|---|---|---|---|
| landscape | [48.16 MB](out/montage_landscape.mp4) | [17.33 MB](out/montage_landscape_discord.mp4) | 60.010 s | -0.326 / -0.029 | 148.60 s |
| vertical | [21.02 MB](out/montage_vertical.mp4) | [8.47 MB](out/montage_vertical_discord.mp4) | 30.016 s | -0.952 / -0.138 | 91.72 s |
| mean_vertical | [13.88 MB](out/montage_mean_vertical.mp4) | [5.90 MB](out/montage_mean_vertical_discord.mp4) | 20.031 s | -0.620 / -0.097 | 46.94 s |

The runtime figures above are the final render run, including cached privacy
processing and Discord conversion. The 128-kbps Discord pass can introduce new
AAC overshoot: its exporter now measures decoded floats and repairs gain with
video stream copy when needed. An earlier verification correctly failed at a
1.131 decoded peak; the final run above passed for all six files.

Machine-readable plans, manifest, verification and nine QA frames are in `out/`.
The directory is intentionally gitignored; no video or credential is committed.

## Reproduce

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python ../demo_video/fx2/render_saved.py"
tools/remote_run.sh "cd full_app && python ../demo_video/fx2/verify.py"
```

The demo script reads only saved `planned_*.json` and the existing source from
`/srv/demo_out/demo02/`; it neither re-analyzes footage nor calls Gemini.
It preserves DEMO-02's reviewed cuts and privacy masks. Optional reaction-pack
overlays are disabled to isolate the VFX/SFX change. Seed is 2026. Outputs and
Discord copies live in `/srv/demo_out/fx2/` and local `demo_video/fx2/out/`, which
is gitignored. The output plans, manifest, audio/decode verification and QA
frames are retained beside the videos.

To reroll an existing saved job in Python (from `full_app`):

```python
from services.fx_planning import restack_saved_job
result = restack_saved_job(job, chaos=.7, seed=2027)
job.update(result)  # planner_plan, edit_plan, event table
```

The normal `planner.plan_edit(clips, chaos=.7, seed=2027)` entry point also
accepts the options. To enable Gemini choices, explicitly supply
`refiner=GeminiRefiner(configured_client, model)`; one request supplies both
caption and effect patches, and any invalid patch preserves the local fallback.

## Files changed

- `full_app/models/effects.py`: four additional VFX IDs.
- `full_app/fx/catalog.py`: complete tagged inventory.
- `full_app/planner/{models,planner,adapter,refinement,stacks}.py`: options, events, seeded chooser, single-call refinement and timing adapter.
- `full_app/render/{plan,engine,placements,audio}.py`: validated inputs, timed VFX and shared SFX graph.
- `full_app/services/fx_planning.py`: saved-analysis restacking service.
- `full_app/tests/{test_planner,test_planner_stacks,test_render_stacks}.py`: updated behavioral contract, offline selection tests and real FFmpeg coverage.
- `docs/{fx,planner,rendering}.md`: behavior, options, limitations and reproduction.
- `demo_video/fx2/{.gitignore,catalog.json,render_saved.py,finalize_saved.py,finalize_discord.py,verify.py,REPORT.md,effects.md}`: inventory, reproducible demo/QA, this report and per-clip table.

## Limits

Event times inherited from a scored window remain heuristic unless a detector
supplied a timestamp. Explicit segment speed is exempt from decorative repeat
caps; transitions are counted separately. Asset length tags are recommended
editorial slices, not measured media durations. No optical-flow, new model,
downloaded footage, new SFX asset or extra dependency was introduced.
The shared runner's render timings include privacy masking and Discord encoding;
they are not isolated VFX performance benchmarks. Optional live Gemini behavior
is covered with mocks, not a paid smoke call. Seed reproducibility covers the
local chooser; persist the returned JSON when replaying external Gemini patches.

## Per-clip effects

Times below are output-timeline seconds; source ranges remain in original source seconds.

| Montage / clip | Source seconds | Events (output seconds) | VFX | SFX |
|---|---|---|---|---|
| landscape / clip_0 | 1684.65–1686.65 | clutch @1.30, kill @1.30, multikill @1.30 | hitmarker @1.27, dark_mood @1.32, text_nice @1.32 | rizz @1.30, another_one @1.28, impact_hit @1.30 |
| landscape / clip_1 | 1499.90–1507.90 | kill @7.20, play @7.20 | flash_white @7.23, zoom_in_center @7.22, warm_tint @7.21 | meow @7.20, taco_bell @7.20, agamotto @7.16 |
| landscape / clip_2 | 647.00–657.00 | ability @18.90, kill @18.90, multikill @18.90, play @18.90 | zoom_punch @18.90, moderate_grain @18.91, contrast_pop @18.94 | deku_hero @18.93, stand_ready @18.89 |
| landscape / clip_3 | 567.67–577.67 | kill @26.98, multikill @26.98, play @26.98 | shake @26.98, cold_tint @27.02, warm_tint @26.98, text_gg @26.99 | again_again @27.00, i_will_eliminate_you @27.02, im_better @26.95 |
| landscape / clip_4 | 912.50–917.50 | clutch @35.80 | slow_motion @30.00, text_clutch @35.79, zoom_in_center @35.76 | bye_bye_mewing @35.81, hello_there @35.81, movie_clip @35.82 |
| landscape / clip_5 | 1404.20–1414.20 | ability @46.50, kill @46.50, multikill @46.50, play @46.50 | flash_white @46.51, moderate_grain @46.50 | surprise @46.48, knight_shining_armor @46.47, za_warudo @46.46 |
| landscape / clip_6 | 1682.70–1687.70 | clutch @56.50, kill @56.50, multikill @56.50 | slow_motion @50.00, shake @56.50, heavy_sharpen @56.49 | anime_wow @56.50, jojos_golden_wind @56.51, another_one @56.54 |
| vertical / clip_0 | 1684.65–1686.65 | clutch @1.30, kill @1.30, multikill @1.30 | hitmarker @1.27, dark_mood @1.32, text_nice @1.32 | rizz @1.30, another_one @1.28, impact_hit @1.30 |
| vertical / clip_1 | 912.80–916.80 | clutch @7.20 | slow_motion @2.00, cold_tint @7.20, text_clutch @7.16, saturation_boost @7.19 | prowler @7.21, homelander_yummers @7.24, agamotto @7.17 |
| vertical / clip_2 | 1404.20–1414.20 | ability @16.50, kill @16.50, multikill @16.50, play @16.50 | shake @16.50, moderate_grain @16.51 | jojos_golden_wind @16.51, i_will_eliminate_you @16.50 |
| vertical / clip_3 | 1682.70–1687.70 | clutch @26.50, kill @26.50, multikill @26.50 | slow_motion @20.00, flash_white @26.46, cold_tint @26.50 | knight_shining_armor @26.53, stand_ready @26.48, outro_song @26.50 |
| mean_vertical / clip_0 | 134.70–136.70 | death @1.30, fail @1.30 | text_oof @1.24, deep_fry @1.34, black_and_white @1.34, desaturate @1.24 | spongebob_fail @1.26, you_are_an_idiot @1.37, sad_cat @1.27, thats_rough @1.31 |
| mean_vertical / clip_1 | 1684.97–1686.47 | clutch @3.95, kill @3.95, multikill @3.95 | slow_motion @2.00, shake @3.94, bright_boost @3.89, text_gg @3.96 | taco_bell @3.95, agamotto @3.90, za_warudo @3.89, knight_shining_armor @3.91, homelander_yummers @3.95 |
| mean_vertical / clip_2 | 264.75–269.75 | ability @8.25, death @8.25, fail @8.25 | text_bruh @8.22, freeze @8.25, moderate_sharpen @8.22, flash_white @8.27 | should_have_died @8.22, nemesis @8.29, thats_rough @8.22, cinematic_boom @8.29, yowai_mo @8.32 |
| mean_vertical / clip_3 | 129.50–139.50 | death @16.50, fail @16.50 | text_rip @16.44, deep_fry @16.49, shake @16.51, moderate_blur @16.54 | my_leg @16.52, leave_me_alone @16.54, roblox_death @16.45, you_are_an_idiot @16.55 |
