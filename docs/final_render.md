# FINAL-1 combined replay

The implementation exposes chaos/seed over HTTP and the production UI, sizes
visible reaction heads after cropping transparent padding, and supports explicit
pack metadata with an independent clean filter. The review Reroll button replans
locally, reuses analysis, disables the paid Director, and displays new VFX/SFX.

## Reproduce on runner 1

```sh
tools/remote_run.sh "cd full_app && python -u ../demo_video/final/render_saved.py"
tools/remote_run.sh "python demo_video/final/verify.py"
tools/remote_run.sh "cd full_app && python -m pytest -q"
tools/remote_run.sh "cd full_app/production_frontend && npm ci --silent && npm test && npm run build"
```

The replay also accepts `--only landscape`, `--only vertical`,
`--only mean_vertical`, or `--only mean_vertical_reroll`. It reads the existing
78-clip DEMO-02 analysis and source under `/srv/demo_out/demo02/`; provider access
is explicitly blocked. No credential file is read. The mean target is increased
from the old saved 20-second plan to 30 seconds using the same saved evidence.

Outputs go to `/srv/demo_out/final/`, with local copies in
`demo_video/final/out/` (gitignored). Each variant has a master, Discord copy,
saved plan, final job with execution evidence, reaction frames and spotlight
frames. Verification produces `clips.md`, `contact_sheet.jpg`, hashes, decode
results, audio peaks and reroll reproducibility checks.

## Choices and dependencies

- Nice chaos .35; mean chaos .6. Seed 2026; mean reroll seed 2027.
- Full experience, privacy false, large matted heads from `/srv/packs/team`.
  Clean is false for the demos; nice still prefers non-explicit clips.
- All four speakers rotate before reuse, with event labels varied across clips.
  The demo allows up to 2.8 seconds per reaction when there is room; actual
  playback is bounded by each original pack clip's duration.
- Local SAM 2.1 small: `/srv/models/sam2.1_hiera_small.pt`, config
  `configs/sam2.1/sam2.1_hiera_s.yaml`, CPU, four mask samples per clip,
  120-second request timeout and 300-second clip budget. The ordinary app keeps
  its existing 12-sample default; `SAM_MAX_SAMPLES` is configurable in [1,240].
  Landscape retains the entire frame, so subject crop tracking is disabled there;
  SAM spotlights remain enabled. Vertical uses subject tracking and spotlights.
- Optional dependencies were installed into the task runner venv using
  `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`
  and `SAM2_BUILD_CUDA=0 pip install -r full_app/sam/requirements-local.txt`.
  No heavyweight dependency enters the default requirements.
- Music is generated locally, with ducking and beat synchronization. The end
  card accounts for beat trimming, frame rounding and crossfade overlap to hit
  the requested 60/30-second total without extending source ranges.
- SAM evidence records only successful real-model spotlights. Missing models or
  exhausted budgets warn and skip; they are never reported as working inference.
  Sparse masks and heuristic source event timing remain approximations.
  Visual inspection of landscape spotlights found that the generic seed can
  select the weapon or scenery, rather than isolating an enemy. These are real
  SAM composites at event times, not reliable enemy tracking.
- Speech captions may fall back to explicitly labelled editorial words. Local
  narration only plays in safe gaps; it may skip clips with insufficient space.

See `demo_video/final/REPORT.md` for final measurements, test results, commit IDs
and visual inspection findings.
