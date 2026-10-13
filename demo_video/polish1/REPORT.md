# POLISH-1 delivery

Branch: `ext/POLISH-1`. Implementation milestones: `bd8d91a` (copy/layout/cards),
`fba08f4` (crossfade boundaries), `5378347` (user-caption compatibility). No push or merge.

## Changes

- `full_app/pipeline/ranking.py`: missing signal descriptions become empty metadata.
- `full_app/planner/planner.py`, `refinement.py`: source descriptions are never copied into display text; event-derived editorial lines and refinements obey the five-word limit.
- `full_app/pipeline/rendering.py`: removes descriptions from saved plans and records executed text reservations.
- `full_app/render/text_layout.py`, `engine.py`, `captions.py`: resolves text collisions before composition, suppresses internal/default labels and long editorial text, keeps speech separate, and fits captions within their horizontal margins.
- `full_app/fx/bold.py`: moves NEXT TIME away from the caption band.
- `full_app/cards/rendering.py`: composes cached artwork for landscape, portrait, and square using a blurred cover fill behind intact lettering.
- `full_app/tests/test_polish1.py`: regressions for all five task findings, including actual FFmpeg card encodes.
- `docs/cards.md`, `docs/rendering.md`: behavior and reproduction documentation.
- `demo_video/polish1/`: offline reproduction, fetch script, Deadlock evidence, and this report. Media and job data stay in ignored `out/`.

## Decisions and limitations

Descriptions remain in the analysis and share kit/chapters. Saved analysis and cuts are reused; old description captions are omitted instead of inventing claims about the gameplay. New plans use short event-derived lines. Speech is not subject to the editorial word limit.

Collision reservations are conservative: unknown text FX reserve the whole frame, and reactions reserve their corner. Lower-priority text can be omitted for its entire event. Graphic hit markers/particles are excluded from editorial text reservations. This preserves the NO SHOT pop while removing the internal label below it.
Copy and reactions are trimmed out of crossfade windows. The first real timeline
audit caught an outgoing reaction at 4.57–5.17 seconds overlapping incoming
speech at 5.03 seconds; this is now covered by an encoded two-clip regression.

The current thumbnail client fixes its image request to 16:9 and is outside this task's allowed paths. The supported composition fallback fills portrait/square output without cropping away generated lettering. All four Valorant AI cards are reused; no Gemini calls or credentials are needed.

Deadlock's saved outro manifest reports only `reason: provider`; its earlier job error is a separate generic render failure. There is no recorded timeout, safety, HTTP, or budget evidence from which to diagnose an application cause. The cached, visible fish/car fallback remains. See [deadlock_fallback.json](deadlock_fallback.json). No image attempts were reset or retried.

## Reproduce

On the configured runner, using FINAL-2's existing optional ML environment and saved media:

```sh
bash tools/remote_run.sh "/srv/lim/lim-final2/.venv/bin/python demo_video/polish1/render_saved.py > /srv/demo_out/polish1-render.log 2>&1"
bash demo_video/polish1/fetch.sh
```

The script forbids provider construction, reuses FINAL-2 job analysis/plans/cards,
and regenerates local share covers, music and narration. SAM and cached local
speech models use the same environment as FINAL-2. Runner outputs live under
`/srv/demo_out/polish1/`; local deliverables live under `demo_video/polish1/out/`.

## Validation

| Cut | Duration / cap | Master MB | Discord MB | Reviewed samples / sheets |
|---|---:|---:|---:|---:|
| [Valorant nice landscape](out/valorant_nice_landscape/) | 58.721 / 60 s | 55.75 | 17.05 | 55 / 3 |
| [Valorant mean vertical](out/valorant_mean_vertical/) | 29.054 / 30 s | 18.66 | 8.49 | 33 / 2 |

Both masters and Discord copies decoded completely with `ffmpeg -xerror`.
Both continuous-interval timeline collision audits passed. All five contact
sheets (88 samples) were inspected, plus full-size portrait intro/outro frames;
no internal labels, full-description subtitles, generated-text overlaps or black
card padding were seen. Intentional gameplay clutch bars remain. See
[visual_review.json](visual_review.json) for per-sheet findings.

Gemini calls: **0 / 6**. Each output contains `master.mp4`, `discord.mp4`,
`job.json`, `planned.json`, `verification.json`, timings, cards, share kit, and
contact sheets. The final render command above completed with **exit 0**, as did
`bash demo_video/polish1/fetch.sh`. The last compatibility fix only changes clips
with explicit user-caption fields; both delivered jobs have zero such fields,
so it does not change their rendering.

Remaining warnings are the existing local SAM rejection when tracking is
unstable/fragmented, absent speech words in some clips, one narration line that
does not fit a safe gap, and intentionally disabled AI share thumbnails.
Share covers are local to keep provider use at zero. Source analysis
descriptions remain in metadata/share chapters. No requested coding work remains;
the undiagnosed Deadlock provider failure retains its visible cached fallback.

Final code validation:

```sh
bash tools/remote_run.sh "cd full_app && python -m pytest -q > /srv/demo_out/polish1/pytest.log 2>&1"
```

**1,453 passed, 20 skipped; exit 0** (635.68 seconds). The final log is copied to
`out/pytest.log`. Frontend validation below also passed: **44 tests and production
build; exit 0**. The saved clips, planner plan and original edit plan were compared
before/after for both deliverables and are unchanged. All four cached Valorant
card manifests remain AI successes, with no extra image attempts.

Recorded development commands:

- `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_cards.py tests/test_planner_adapter.py tests/test_render_stacks.py tests/test_final1.py"`: 109 passed, 4 failed, exit 1. Fixed nullable effect-filter handling.
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_polish1.py tests/test_planner_adapter.py"`: 15 passed, 2 failed, exit 1. Fixed the new pixel-test seek timestamp from `.1` to `0.1`.
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_polish1.py tests/test_cards.py tests/test_planner_adapter.py tests/test_planner.py"`: 69 passed, exit 0.
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q"`: initial full run, 1,449 passed, 20 skipped, exit 0 (before the added crossfade regression).
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_polish1.py tests/test_render_fix.py tests/test_render_v2.py tests/test_planner_adapter.py"`: 58 passed, exit 0, including the crossfade fix.
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q > /srv/demo_out/polish1/pytest.log 2>&1"`: first complete crossfade revision run had 1,452 passed, 20 skipped, 1 failed, exit 1. Fixed explicit user-caption compatibility.
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_pipeline_settings.py tests/test_polish1.py"`: 16 passed, exit 0, including that compatibility fix.
- `bash tools/remote_run.sh "cd full_app/production_frontend && npm ci --silent && npm test && npm run build"`: 44 tests passed; TypeScript/Vite production build passed; exit 0.
- An initial preview render was deliberately stopped (exit 143) after refining graphic-hitmarker classification. It is superseded by the final render.
- The next preview's global collision assertion failed (exit 1), revealing the crossfade issue. A superseded full-suite rerun was stopped (exit 143) to test the fix on the final code instead.

Visual review is sampled contact-sheet inspection, not frame-by-frame human playback. Full decode checks and continuous-interval text-box collision checks supplement the visual review.
