# Local talking-head reactions

The opt-in `full_app/reactions` module needs only Python, FFmpeg and ffprobe (FFmpeg
with libx264, AAC and drawtext/font support for optional names). No API calls or ML
dependencies are used. Existing montage behavior is unchanged until the backend
calls the hook.

## Pack format

Put packs in `full_app/reaction_packs/<name>/` (already gitignored). Never commit
real faces, voices or generated media. `pack.json` is UTF-8:

```json
{"version": 1, "clips": [
  {"id": "alex-kill-01", "speaker": "Alex", "label": "sick_kill",
   "text": "Sick kill!", "file": "alex-kill-01.mp4", "duration": 1.2,
   "background": "light", "alpha_file": "alex-kill-01.alpha.webm",
   "mask_file": "alex-kill-01.mask.mp4"}
]}
```

IDs must be unique; files must resolve within the pack (including symlinks).
Duration is positive seconds. Labels: `sick_kill`, `clutch`, `bruh`, `fail`,
`funny`, `wholesome`, `hype`, `roast`. Background is `light` (white/light key),
`transparent` (preserve source alpha), or `opaque` (circle crop only). Square,
centered portraits work best; other aspect ratios fit within the overlay square.
The legacy light key also removes near-white foreground details; use the offline
matte workflow below for these avatars. Optional matte paths have the same containment
and symlink validation as originals. Other manifest metadata is preserved.

From Village, export each authorized avatar/voice reaction as a short, synchronized
video with audible voice, preferably a clean light background or alpha. Trim idle
lead/trail time, normalize voice levels, give every variation a unique ID and label,
and measure duration with `ffprobe -v error -show_entries format=duration clip.mp4`.
Copy exports into the ignored pack folder and create its manifest. Export multiple
speakers and takes per label for rotation. The integrator builds the real pack locally.

## Try the synthetic pack

From `full_app`:

```sh
python -m reactions.demo
python -m pytest -q tests/test_reactions.py
```

The generator creates four tiny colored-circle avatars with moving mouths and beep
audio. Only generator code is shipped; tests generate everything in temporary folders.

## Backend integration

```python
from reactions import load_pack, ReactionSelector, apply_reaction

selector = ReactionSelector(load_pack('reaction_packs/synthetic'), seed=42)
# One selector per montage, reused sequentially for each rendered segment:
path = apply_reaction(segment_path,
    {'label': 'sick_kill', 'score': 0.9, 'peak_time': 1.4,
     'suggested_reaction_label': 'sick_kill'},
    selector, preset='landscape', enabled=True, mode='nice', show_speaker=True)
# Pass path to the existing segment concatenation step.
```

Call after segment timing/speed/effects are final and before concatenation. The
peak is local seconds in that final segment: convert source timestamps by subtracting
the trim start and dividing by playback speed. Without a peak, use the midpoint.
The reaction starts at the peak, shifted earlier when needed to fit before the end;
long reactions are trimmed to the base duration. Scores are expected on [0, 1].
Nice mode excludes roast; mean mode allows all labels and defaults to roast.
Valid VLM suggestions outrank clip labels, then fallback uses score/mode. Never
repeat an ID consecutively; when no alternative exists, skip the overlay. Rotate
speakers within the preferred label when possible, then favor less-used takes.
The same speaker may recur if only that speaker covers the preferred label.

`render_overlay(base_clip, reaction, preset) -> Path` also works directly; keyword
options are `peak_time`, `show_speaker`, `duck_gain` (default 0.25) and `output_path`.
Unique output filenames prevent collisions. Existing outputs are never overwritten.
Errors propagate so the backend can report them; disabled/empty hooks return the base.

Landscape uses bottom-right; vertical uses top-left to leave lower caption space.
The renderer preserves base dimensions, uses 30% of the smaller dimension,
4% margin, soft offset shadow, short fade/bounce transitions and a subtle idle bob.
Matted portraits retain their full silhouette; legacy portraits retain the circular crop.
Matted portraits show a name tag by default; `show_speaker=False` disables it.
Legacy portraits still default to no name tag. The tag follows the motion. It does not convert
landscape to portrait: supply a segment already rendered at the desired aspect ratio.
Game audio is ducked during the voice clip; voice is mixed at original gain with a
limiter. Silent bases get an audio track; silent reactions do not duck game audio.
Speaker text is read literally from a temporary file, never interpolated as a filter.

Tests probe output duration/dimensions/audio streams, inspect decoded frames before,
during and after the reaction and at mask corners, and measure game/voice frequency
amplitudes to check ducking and recovery. Local packs are trusted media; untrusted
uploads still need the backend's normal resource limits. Rendering re-encodes video
and audio and requires enough disk space for a new segment.

## Offline pack matting (REACT-2)

From the repository root on a machine with the app's NumPy/OpenCV dependencies and
FFmpeg built with libvpx-vp9/libx264:

```sh
python tools/matte_pack.py /srv/packs/team --qa-dir /srv/demo_out/react2/checks --report /srv/demo_out/react2/timings.json
# Watch a batch being appended, every five minutes for at most 45 minutes:
python tools/matte_pack.py /srv/packs/team --wait-for 80 --wait-minutes 45 --poll-seconds 300 --report /srv/demo_out/react2/watch.json
```

Every `background: light` clip gets `<id>.alpha.webm` (VP9 alpha, decontaminated RGB)
and `<id>.mask.mp4` (lossless grayscale H.264). Original media and audio are unchanged.
The manifest gains relative `alpha_file` and `mask_file` paths only after encoding
succeeds. Outputs are staged in the pack, and each manifest update re-reads the latest
clips so a batch appended during a long encode is retained. Use a single matte writer;
an external manifest writer should also merge the latest data and publish atomically.
Clips with existing matte assets are skipped. `--force` regenerates the first pass;
`--only iraj-bruh lance-bruh` limits work to selected IDs. Exit 2 means the watch
deadline expired before the target was fully matted. Each completed clip logs its ID,
frame count and wall-clock seconds, including encoding and optional QA generation.

The key estimates the light background gradient from the side borders, finds connected
background regions, preserves enclosed light details, and estimates fractional edge
coverage from nearby opaque foreground colors. It removes background color from RGB
edges and smooths only small inter-frame changes, avoiding moving-head trails. Tune
`--low` (default 10), `--high` (65), and `--smoothing` (0.25) for other packs.
Clean light side borders and constant-rate input are required. Variable frame rates
are rejected instead of silently changing timing. Mask and alpha outputs have exactly
one frame per source video frame at its original rate. Audio always comes from the
original clip, so alpha-only video never loses the voice or disables ducking.

Optional `--sam-local` uses the existing local SAM2 adapter to refine the foreground
seed. Install the existing `full_app/sam/requirements-local.txt` extras and set
`SAM2_CHECKPOINT` for that path. Missing dependencies/checkpoints gracefully fall back
to the deterministic key. There are no remote model calls or automatic model downloads.
The color key is the default and needs no ML extras.

Renderer priority is alpha, then mask, then legacy behavior. VP9 alpha is explicitly
decoded with libvpx-vp9 because native VP9 decoders may discard the alpha plane.
Prefer alpha assets: mask-only assets retain the original edge RGB.
The default uses OpenCV's bundled offline face detector on three frames and a fixed,
median face box to feather a jaw contour, excluding shoulders while retaining upper
hair, glasses and beards. This does not introduce moving crop jitter. `--portrait`
keeps the full source silhouette instead. When no face is detected, the tool preserves
the silhouette and reports `head_box: null`; review those clips manually. Long hair
below the jaw is clipped by the head contour. Soft Gaussian-splat source
edges can need per-pack tuning; inspect the QA stills before distributing a new pack.

QA sheets show original / dark synthetic gameplay pattern / bright synthetic gameplay
pattern, at the first, middle and near-final frame. They include no downloaded gameplay.
Keep faces, voices, masks and all QA media outside git. Local review artifacts belong in
`demo_video/react2/`, with a local `*` ignore file; nothing in that directory is committed.

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_reactions.py tests/test_reaction_matte.py"
tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"
```

Synthetic tests cover enclosed glasses, fine hair and beard detail, moving-head trail
avoidance, idempotency, path validation, matte frame count, before/during/after output,
both matte formats across 16:9 / 9:16 / 1:1, name tags, original voice sync and ducking.

For final decoded-video QA (all four speakers, three presets, dark and bright frames),
use existing authorized gameplay, or omit `--gameplay` for synthetic test patterns:

```sh
cd full_app
python -m reactions.qa /srv/packs/team /srv/demo_out/react2/gameplay --gameplay /path/to/gameplay.mp4
```

This creates 24 short videos and before/after stills. Still panels are original reaction,
gameplay before, gameplay after; outputs remain private. The QA directory must be new
to prevent accidentally overwriting an earlier review.

## Runner 1 completion, 2026-10-12

The team pack at `/srv/packs/team/` reached 80 clips (the original 32 plus all 48
new clips). All 80 have both alpha and mask assets and a detected head box. The
five-minute watcher finished successfully within the requested 45-minute window.
The producer refreshed some manifest entries while appending; a subsequent pass
reconciled those entries before reporting success. Originals were retained.

Final per-clip processing time, including encoding and three QA sheets: mean 5.844 s,
minimum 3.698 s, maximum 9.563 s, sum 467.530 s across the final 80 outputs. These
numbers exclude earlier tuning passes and polling waits. Full event timings are in
`/srv/demo_out/react2/head-timings.json`; local final timings are in
`demo_video/react2/timings.csv`. All these artifacts are intentionally untracked.

Recorded validation commands from the Windows worktree (Git Bash via `bash`):

```sh
bash tools/remote_run.sh "cd full_app && python -m pytest -q -m not\ live"
# exit 0: 1052 passed, 19 skipped, 1 deselected; 878.59 seconds
bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_reaction_matte.py tests/test_reactions.py"
# exit 0 on the final implementation: 27 passed; 41.97 seconds
bash tools/remote_run.sh "python tools/matte_pack.py /srv/packs/team --report /srv/demo_out/react2/idempotent.json"
# exit 0: pack clips=80; existing mattes skipped
```

A separate FFprobe/FFmpeg audit exited 0: all 80 alpha/mask pairs match their
original dimensions, frame rates and frame counts (2,430 video frames total).
Forced libvpx decoding confirmed both transparent and opaque pixels in every
alpha asset. Each speaker has 20 entries. The real-pack idempotency report has
80 skipped entries and no regenerated clips. Audit details are saved privately in
`/srv/demo_out/react2/verified.json` and `demo_video/react2/verified.json`.

The broad suite ran during implementation; the final focused run includes the later
head contour, watcher reconciliation and failure-recovery tests. No paid/live calls
were made, and no API credentials were read. Local SAM2 weights were not exercised.

Decoded gameplay QA completed with exit 0 using `python -m reactions.qa`, all four
speakers, all three presets and both bright/dark gameplay. Its 24 videos and 24
original/before/after stills are at `/srv/demo_out/react2/head-gameplay/` and copied
locally to `demo_video/react2/final/`. Fine source hair remains soft; the jaw contour
is heuristic and intentionally trims long hair below the jaw. Other packs need the
same visual review, especially profiles, moving subjects or long beards.
