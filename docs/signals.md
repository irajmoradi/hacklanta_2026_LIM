# Local candidate detection

From `full_app`, install `requirements.txt` and ensure `ffmpeg`/`ffprobe` are on PATH:

```sh
python -m signals gameplay.mp4
python -m signals gameplay.mp4 --profile valorant --ocr
python -m signals gameplay.mp4 --config '{"pre_roll": 2, "max_length": 15, "weights": {"motion": 0.5}}'
```

```python
from signals import detect_candidates

candidates = detect_candidates("gameplay.mp4", profile="auto", peak_threshold=0.65)
payload = [candidate.to_dict() for candidate in candidates]
```

The result is a score-ranked list of `Candidate(start, end, score, signals, events)`
dataclasses. `to_dict()` produces JSON-compatible dictionaries. Times are seconds
from the beginning of the video; end is exclusive. Ties sort by start time.
`signals` contains the maximum per-second **z-score** for each feature within the
window; `score` is the maximum weighted interest in that window (not a probability).
The CLI writes only JSON to stdout, optional-dependency warnings to stderr, and
returns 2 on invalid input/decoder errors. Silent static input returns `[]`.
Nothing calls Gemini, accesses a network, downloads weights, or modifies the input.
This is an additive proposal API: the existing upload/analyze/plan/render flow is
unchanged; integration into that flow is outside EXT-01's allowed paths.

## Features and fusion

Video is decoded once and sampled at 4 fps, downscaled to 320 pixels wide. OpenCV
frame differences give mean absolute grayscale change (0–1) per second. Scene
detection uses optional PySceneDetect AdaptiveDetector when installed (`auto`),
or FFmpeg scene scores >0.30 otherwise. Select `content`, `adaptive`, or `ffmpeg`
explicitly to control the backend. Missing PySceneDetect falls back with a warning
for explicit requests. Both backends operate on sampled frames: sub-250 ms events
can be missed. FFmpeg computes scene scores in the shared frame extraction filter,
retaining frames for motion instead of doing another full decode. See the
[FFmpeg filters documentation](https://ffmpeg.org/ffmpeg-filters.html) and
[PySceneDetect detectors](https://www.scenedetect.com/docs/latest/api/detectors.html).

Audio uses FFmpeg `astats` on 100 ms, 8 kHz mono blocks. Linear RMS is aggregated
per second; positive block RMS changes give onset strength. Runs at least 0.5 s
above max(0.025 RMS, 2.5 × median RMS) produce `sustained_audio` events and a
per-second occupancy feature. This identifies loud bursts, not semantic gunfire,
laughter or speech. Missing audio yields zeros; malformed media raises an error.

Each feature is independently z-scored over the entire recording. Constant
features contribute zero. Weights multiply signed z-scores; partial overrides
retain other defaults and a weight of zero disables a feature:

| Feature | Weight |
| --- | ---: |
| scene | 0.15 |
| rms | 0.25 |
| onset | 0.15 |
| sustained | 0.15 |
| motion | 0.30 |
| ocr | 0.70 |

Local maxima above 0.65 generate windows with 3 s pre-roll and 4 s post-roll.
Overlaps and gaps up to 1 s merge. Low-motion (<0.008) and low-audio (<0.012 RMS)
edge seconds trim away unless they contain a scene/OCR event. Minimum duration is
then restored (3 s), so a little dead air can remain. Maximum duration is 20 s:
long merged windows split into balanced pieces retaining peaks. When min/max
bounds cannot partition a window, the strongest nonoverlapping peak windows win.
Clips shorter than the minimum use the available duration. Up to 30 nonoverlapping
windows are returned; minimum-length expansion conflicts keep the stronger window.

## OCR and game profiles

OCR is opt-in (`ocr=True`/`--ocr`) and uses the optional **Tesseract executable**
with English language data. No Python OCR dependency is required. On Debian/Ubuntu
install `tesseract-ocr`; absent binaries or OCR failures warn and continue without
OCR. Optional scene support: `pip install 'scenedetect>=0.6.7,<0.8'`.
Neither optional component is a required application dependency.

OCR samples at `sample_fps` (2–4 fps), at `ocr_width=960`, crops normalized regions,
and upscales crops 2×. Static crops skip repeat OCR. Kill/death text is deduplicated
with a 3 s cooldown; death phrases take precedence over kill phrases. Recognized
phrases include `ELIMINATED`, `KILLED`, `KILLED BY`, `ELIMINATED BY`, and `YOU DIED`.
Events include `time`, `type`, `text`, and `region`. Icon-only kill feeds are not
interpreted as confirmed kills; this text heuristic cannot reliably attribute a
feed entry to the player. A moving background can trigger frequent OCR calls.

| Profile | Kill feed (left, top, right, bottom) | Banner |
| --- | --- | --- |
| auto | .62, .02, 1, .32 | .20, .35, .80, .75 |
| valorant | .64, .03, 1, .30 | .25, .42, .75, .80 |
| overwatch2 | .64, .02, 1, .30 | .23, .43, .77, .75 |
| deadlock | .62, .03, 1, .33 | .20, .35, .80, .75 |

These are configurable starting regions, not learned game-specific detectors.
`auto` selects generic regions; it does not infer the game. Spaces, underscores and
hyphens in profile names are ignored. Override regions with e.g.
`ocr_regions={"banner": (0.1, 0.3, 0.9, 0.8)}` (replaces the default regions).

## Configuration and validation

All `Config` fields are accepted as keyword arguments. Besides the values above:
`width=320`, `threads=4`, `scene_threshold=0.30`, `ocr_cooldown=3`,
`merge_gap=1`, `dead_motion=0.008`, `dead_audio=0.012`,
`trim_dead_air=True`, `max_candidates=30`. Thresholds and weights must be finite
and nonnegative; lengths positive with max >= min; unknown fields/profiles fail
early. `threads` limits each FFmpeg decoder; audio and video extract concurrently.

Run tests from the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q"
tools/remote_run.sh "cd full_app && RUN_SIGNALS_BENCHMARK=1 python -m pytest tests/test_signals_benchmark.py -s -q"
```

Tests synthesize `testsrc2`, sine spikes, hard cuts and `drawtext` banners in pytest
temporary directories. OCR tests skip only if Tesseract is unavailable. The opt-in
benchmark generates a 600 s 1080p30 H.264 recording, limits affinity to at most 12
cores, and asserts detection <60 s for both `ffmpeg` and `auto` (generation excluded). The speed target covers
the default cheap signals; OCR is slower and is excluded. Actual speed depends on
codec, frame rate, CPU and scene complexity. No paid live tests are necessary.

### EXT-01 validation record

Linux runner, 2026-10-12, using `bash tools/remote_run.sh` from the worktree root:

| Remote command | Result | Exit |
| --- | --- | ---: |
| `cd full_app && python -m pytest -q` (initial implementation) | 19 passed, including real Tesseract OCR | 0 |
| `cd full_app && RUN_SIGNALS_BENCHMARK=1 python -m pytest -q -s` (initial benchmark) | 20 passed; 600 s 1080p30 in 27.483 s, 12 cores | 0 |
| `cd full_app && pip install -q scenedetect==0.7.1 && python -m pytest -q` (compatibility probe) | 1 failed, 20 passed, 1 skipped; revealed 0.7 FrameTimecode API change, subsequently fixed | 1 |
| `cd full_app && pip install -q scenedetect==0.6.7 && python -m pytest -q && pip install -q scenedetect==0.7.1 && RUN_SIGNALS_BENCHMARK=1 python -m pytest -q -s` | 0.6.7: 24 passed, 1 benchmark skipped; 0.7.1: 25 passed including benchmark, FFmpeg detection 25.425 s on 12 cores | 0 |
| `cd full_app && RUN_SIGNALS_BENCHMARK=1 python -m pytest tests/test_signals_benchmark.py -k auto -s -q` | 1 passed, 1 deselected; automatic PySceneDetect 0.7.1 detection 26.746 s on 12 cores | 0 |

The optional packages were installed only in the runner's task venv. No application
API calls were made and no secret was read. The performance numbers describe the
synthetic H.264 benchmark, not a guarantee for every gameplay codec or OCR workload.
