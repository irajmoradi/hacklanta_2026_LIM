# SAMFIX-1

Branch: `ext/SAMFIX-1`. No pushes or merges. Gemini/live provider calls: **0**.
No credential file was read. All changes stay within the task's allowed paths.

## Changes

- `e25542f`: event-local SAM point/box prompts, conservative mask rejection,
  feathered spotlight, visible reaction-head sizing and offline tests.
- `391f9b1`: exact kill-frame sampling, bounded-duration and job-warning tests,
  saved-analysis replay, verification script and API documentation.
- The final report commit records the verified artifacts and visual review.

SAM spotlights now use the crosshair plus a small spatial box near the supplied
kill time. They reject masks that are too big/small, hit frame edges, HUD or the
player's weapon region, miss the crosshair, fragment, or fail temporal IoU.
Unavailable models and insufficient temporal evidence also skip. Rejection
leaves ordinary gameplay, emits a job warning and suppresses freeze insertion.
Accepted effects have morphological closing, feathered edges, soft warm glow
and mild background dim/desaturation, with a 0.6-second cap.

Large heads size the visible opaque silhouette at 35% of landscape height, 28%
of vertical width and 32% of square height before feather padding/edge overlap.
Disconnected matte dust and faint halos no longer enlarge the crop and shrink
the actual face. Existing head-only matte, shadow, bounce, bob, name and audio
ducking behavior remain. Medium and small retain .78/.55 multipliers.

## Validation

Commands below ran from the worktree root, on Linux through the required helper.

| Command | Result |
|---|---|
| `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_sam.py tests/test_sam_targeting.py tests/test_reactions.py tests/test_reaction_matte.py tests/test_reaction_sizes.py tests/test_final1.py"` | 91 passed, exit 0; 60.38 s. Earlier milestone run: 89 passed, exit 0. |
| `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_wire1.py tests/test_pipeline.py tests/test_pipeline_settings.py tests/test_render_v2.py"` | 92 passed, exit 0; 200.14 s. |
| `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_sam_targeting.py"` | Final exact-kill-frame revision: 16 passed, exit 0; 5.89 s. |
| `bash tools/remote_run.sh "python -u demo_video/samfix/render_saved.py --only landscape > /srv/demo_out/samfix-landscape-final.log 2>&1"` | Final local-SAM landscape replay, exit 0; 457.92 s. |
| `bash tools/remote_run.sh "python -u demo_video/samfix/render_saved.py --only mean_vertical > /srv/demo_out/samfix-vertical-final.log 2>&1"` | Final local-SAM mean portrait replay, exit 0; 329.99 s. |
| `bash tools/remote_run.sh "python demo_video/samfix/finalize.py && python demo_video/samfix/verify.py"` | Four full video decodes, duration/geometry, audio peak, head sizes and Discord limits passed, exit 0. |
| `bash demo_video/samfix/fetch.sh` | Copied artifacts locally; all four SHA-256 checks passed, exit 0. |

Tests use generated synthetic video and mocked segmentation/provider responses.
They cover each rejection rule, local spatial-prompt arguments, profile centers,
accepted/skip durations, decoded frame changes, actual job warning propagation,
all reaction preset/size placements, alpha/mask rendering and audio ducking.
Existing unregistered `slow` pytest marker warnings remain. No full-suite result
is claimed. The separate saved-gameplay replay exercises real local SAM2.

Runner setup (exit 0):

```sh
bash tools/remote_run.sh "pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && pip install -r full_app/sam/requirements-local.txt"
```

The initial package-presence diagnostic exited 1 because SAM2 was absent. An
initial inline Python import probe also exited 1 due to shell quoting; neither
was a test run. CPU torch and SAM2 were then installed successfully in this
worktree's runner venv. Existing weights: `/srv/models/sam2.1_hiera_small.pt`.

An initial full draft replay also exited 0. Its landscape QA passed. Portrait
QA exited 1 twice while diagnosing decoded AAC peak 1.01575, a small overshoot
after the existing mix/encode stages. A gain-only mastering pass reduced that
master to 0.91070 without re-encoding video. Other exports needed no adjustment.
This is an artifact-only finalization step in the replay script, with an audit
in `out/mastering.json`; no shared audio/pipeline code was changed. The final
commands above passed after that correction.

## Final artifacts and visual QA

Runner artifacts are in `/srv/demo_out/samfix/`; matching local files are in
[out/](out/), gitignored. [Contact sheet](out/contact_sheet.jpg) covers **all six
SAM attempts and all twelve reactions**. [Synthetic before/after](out/synthetic_spotlight.jpg)
shows the accepted compositor's feather and soft glow separately from real-game
skip behavior. Every real SAM attempt was rejected: landscape had two unstable
IoU tracks and one fragmented mask; portrait had two fragmented masks and one
unstable track. All six have explicit job warnings and per-attempt evidence.
This is the task's permitted skip outcome, not a claim of successful enemy masks.

| Final export | Duration | Dimensions | MB | Decoded audio peak |
|---|---:|---|---:|---:|
| [Landscape master](out/montage_landscape.mp4) | 60.010 s | 1920x1080 | 59.44 | .95041 |
| [Landscape Discord](out/montage_landscape_discord.mp4) | 60.010 s | 1280x720 | 16.91 | .91880 |
| [Mean vertical master](out/montage_mean_vertical.mp4) | 30.016 s | 1080x1920 | 20.80 | .91070 |
| [Mean vertical Discord](out/montage_mean_vertical_discord.mp4) | 30.016 s | 720x1280 | 8.16 | .84213 |

Each variant includes Stefanny, Mario, Iraj and Lance. Projecting the actual
selected portrait mattes through the renderer's fixed crop, scale, bob and edge
clipping gives **32.01–32.66% of landscape height** and **26.46–27.08% of portrait
width**, inside the requested ranges. These measurements exclude name tags and
shadows; they are matte/geometry measurements, complemented by decoded-frame
inspection and synthetic decoded-pixel tests. Details: `out/head_measurements.json`.

Reviewed all 18 contact-sheet moments plus the full-size landscape comparison
and synthetic compositor still. Heads remain isolated, readable and anchored at
the bottom corner; the rejected SAM moments show ordinary gameplay instead of
the earlier floor/weapon outlines and heavy darkening. Existing unrelated VFX
are retained. The portrait crop is centered and the normal editorial captions
remain because transcription is unavailable. One portrait narration line still
exceeds its safe speech gap and is intentionally omitted by the existing pipeline.

`out/verification.json`, `out/SHA256SUMS`, job records, manifests and render logs
retain all decode results, hashes, settings, timings and warnings. Both master
hashes match the local copies:

- Landscape: `6fedfca49ae25055eb99d77cabebb2e1d95b728b875a2dc388ca26b9319a1677`
- Mean vertical: `86f50b9308b44d121faab44784d0cb3dc5d780b67aed96b7e3726b643a7eb989`

## Reproduce

```sh
bash tools/remote_run.sh "python -u demo_video/samfix/render_saved.py"
bash tools/remote_run.sh "python demo_video/samfix/verify.py"
bash demo_video/samfix/fetch.sh
```

The replay loads `/srv/demo_out/demo02/planned_landscape.json` and
`planned_mean_vertical.json`, sets `SAM_BACKEND=local`, disables privacy,
uses the existing `/srv/packs/team` matte pack, and blocks pipeline provider
calls. `--only landscape` or `--only mean_vertical` selects one output.
Source clips stay unchanged; the local planner uses seed 2026 and the existing
beat/duration compensation. Saliency reframe is disabled to keep the crosshair
centered in the portrait crop. The 60-second landscape uses nice mode; the
30-second portrait uses mean mode. No source media, heads, voices or weights
are committed.

## Files and limits

- `full_app/sam/{backends,effects,targeting}.py`
- `full_app/reactions/render.py`
- `full_app/tests/{test_sam,test_sam_targeting,test_reaction_sizes}.py`
- `docs/{sam,reactions}.md`
- `demo_video/samfix/{.gitignore,render_saved.py,finalize.py,verify.py,fetch.sh,REPORT.md}`

Profiles currently have no explicit crosshair calibration, so centered FPS aim
is the documented assumption. The API accepts calibrated profile centers,
explicit decoded-frame crosshairs and HUD boxes. Callers using other crops must
transform those coordinates. The conservative FPS weapon/HUD exclusions can
reject legitimate enemies, and geometry cannot prove semantic identity.
The existing pipeline's `render_evidence.sam` records attempts; this replay
adds `accepted` and rejection reasons to distinguish actual effects from skips.
No changes to parallel workers' pipeline, frontend or effects files were made.
