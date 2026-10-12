# Rendering performance toolkit (EXT-10)

The opt-in `full_app/perf/` package requires Python and the existing FFmpeg/ffprobe
installation. It does not modify the production renderer or call Gemini. Run from
`full_app` so the existing `models` and `services` imports resolve.

## Integration

Select **one encoder per montage** with `perf.encoders.best()` and reuse it for
every clip and title. Selection actually encodes a tiny synthetic frame sequence,
trying NVENC, QSV, VAAPI (`/dev/dri/renderD128`), then VideoToolbox. Probe failures,
missing drivers and timeouts fall back to libx264. Results are process-cached;
`best.cache_clear()` retries after device changes. `best(False)` forces CPU.
Hardware availability at startup does not guarantee later session capacity:
if a render fails, retry the whole montage with CPU rather than mix profiles.

```python
from pathlib import Path
from perf.encoders import best
from perf.cache import Cache
from perf.graph import Clip, render
from perf.parallel import render_all
from perf.media import concatenate

encoder = best()
cache = Cache(workspace / "perf-cache")

def render_segment(i, seg):
    clip = Clip(source, workspace / f"fast_{i:03d}.mp4",
                seg["source_start"], seg["source_end"], width, height, fps,
                speed=seg.get("speed", 1),
                transition=seg.get("transition_in", "cut"))
    entries = []
    for entry in seg.get("sound_effects", []):
        path = SOUND_EFFECTS.get(entry.get("sfx_key"), {}).get("file")
        if path and Path(path).is_file():
            entries.append({"file": path,
                            "offset": entry.get("offset_in_segment", 0),
                            "volume": .7})
    return render(clip, seg.get("video_effects", seg.get("video_effect", "none")),
                  entries, "preview", encoder=encoder, cache=cache)

jobs = [lambda i=i, seg=seg: render_segment(i, seg)
        for i, seg in enumerate(edit_plan["segments"])]
paths = render_all(jobs, encoder=encoder, gpu_sessions=2)
output = concatenate(paths, workspace / "final_edit.mp4")
```

For `services/ffmpeg_runner.py`, replace the body of `_render_one_segment` with
the adapter above and return `(i, path)` if retaining its existing interface.
Replace the sequential loop in `render()` with `render_all`; do not then call
`overlay_sfx` or `apply_transition` again. Keep the legacy implementation behind
an opt-in feature flag until integration validation. `single_pass` returns argv
instead of executing it if existing `_run` logging/cancellation is preferred.

For `render/`, map the new renderer's typed timeline into `Clip` plus ordered
registry names and SFX dictionaries. Use `timing="source"` for conventional
source-interval cuts followed by speed retiming. The default `timing="legacy"`
preserves the current renderer's output-time cuts: slow motion does **not** double
the requested duration. Do not silently change modes during integration.
SFX offsets are always output-relative seconds. Supply pre-rendered title jobs
in timeline order to the same worker pool. Existing `image_to_clip` can be used
as a job, but bind its `_encoder_args` to the selected encoder's args and normalize
its dimensions, pixel format, frame rate, SAR, audio layout and video time base
before copy concatenation. VAAPI additionally needs input device and upload
filter arguments, so use its full `Encoder` API rather than only `_encoder_args`.

`render_all` preserves input order and propagates failures. Its cap is the minimum
of four workers, cores divided by per-encoder threads, and (for hardware) the
configured GPU session limit. The default CPU encoder uses at most four threads
per job; both filter-thread settings use the same budget. Set a lower GPU session
limit on shared hardware. Jobs must own different output paths. Exceptions do not
kill subprocesses already running; the pool waits for them before returning.

## Copies, quality and caches

* `media.copy_cut(source, output, start, end)` returns `False` if either boundary
  is not an exact video keyframe (EOF is accepted). It also declines B-frame
  sources, where a timestamp-only check is insufficient. Only call for effect-free,
  speed-1 clips with no normalization requirement. On `False`, encode normally.
  Audio packet rounding may differ by roughly one AAC packet; do not use for
  sample-exact editing. Keyframe scanning costs time on long recordings.
* `media.concatenate` compares all stream signatures, including codec extradata,
  resolution, pixel format, time base and audio layout, before concat-demuxer copy.
  A mismatch raises `ValueError`; normalize the montage inputs explicitly instead
  of producing a corrupt result. Source-copy clips usually cannot be mixed with
  newly encoded clips without normalization. Both old and new concat avoid a
  final encode; there is no additional final-encode saving to claim.
* Preview uses libx264 `veryfast`, draft uses `superfast`, both with `fastdecode`;
  final uses `faster`, CRF 22. No two-pass encode. These settings trade compression
  and quality for speed, so compare final visual quality for the intended content.
* Effects retain registry category ordering. Complex chromatic splitting is
  labeled within the same graph, then normalized back to target dimensions. The
  old chromatic path outputs width minus four pixels; this helper deliberately
  fixes that inconsistency. The existing `fade_out` registry no-op remains a no-op.
  Unknown effects/transitions fail explicitly. Silent sources get stereo silence.
* `Clip(..., cheap_blur=True)` enables quarter-size box blur for moderate/heavy
  blur, then scales back. It is an **approximation**, disabled by default. There is
  no glow effect in the current registry. Neither zscale nor precomputed animation
  is substituted speculatively; measure representative assets before adopting them.
* `Cache.audio` decodes/resamples each SFX once to stereo 48 kHz PCM WAV; the
  one-pass graph delays/mixes these and encodes AAC once. `Cache.proxy` caches
  H.264/AAC 360p30 by default, suitable for repeated analysis and preview decoding.
  Proxies are reusable files, not a shared in-memory decoded-frame cache; final
  exports should still use original media.
* `Cache.overlay(sources, options, build)` atomically caches caller-rendered PNG
  overlays/text. Include fonts in sources and text, dimensions and style in
  options. Existing registry text uses drawtext in the clip graph; overlay caching
  is an integration hook, not an automatic replacement of drawtext.
* Cache keys include absolute source path, size, nanosecond mtime, options and a
  schema version. A shared Cache instance serializes builds and prevents duplicate
  work across threads. Processes may duplicate builds, but atomic replacement
  prevents partial cache hits. Files modified while preserving size/mtime require
  explicit eviction. Cache cleanup/quotas belong to workspace retention policy.

## Reproduce

From the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest tests/test_perf.py -q"
tools/remote_run.sh "cd full_app && python -m perf.bench --seconds 2 --effects --json /tmp/ext10-bench.json"
```

The benchmark generates deterministic-noise testsrc2 at 1920x1080/60 fps plus
sine audio, a synthetic tone and a title bitmap in a temporary directory. No
downloaded media or paid APIs. Input generation and encoder detection are excluded
from stage times. Each effect row measures extraction plus that effect, not its
isolated incremental cost. SFX and transition legacy rows use an existing clip;
their optimized rows include extraction and video encoding, so compare the
end-to-end row for the benefit of combining stages. Cache rows compare cold build
with warm lookup. Concat timings include the new helper's validation overhead.
The end-to-end workload is two two-second clips, heavy blur, GG text, one SFX and
a fade-in per clip, plus concat. Intro/outro are measured separately. Timings are
single wall-clock observations on a shared runner, not statistical guarantees.

## Measured results

Measured 2026-10-12 on Linux 6.8, glibc 2.39, 12 logical cores,
FFmpeg 6.1.1-3ubuntu5. Hardware probes selected libx264; helpers used four encoder
and filter threads per job, with up to three concurrent jobs. The legacy baseline
used its unchanged veryfast/CRF-22/automatic-thread settings. No GPU performance
was measured; hardware selection branches are covered by mocked tests.

Raw observations: [`baseline_linux.json`](../full_app/perf/baseline_linux.json).
A ratio below 1 means the helper was slower. Warm cache values are rounded below;
they were approximately 0.3 ms, so large cache ratios are not throughput promises.

| Stage | Baseline s | Optimized s | Speedup |
|---|---:|---:|---:|
| extraction | 1.017 | 1.453 | 0.70x |
| keyframe cut | 1.083 | 0.531 | 2.04x |
| effect slow_motion | 0.952 | 1.284 | 0.74x |
| effect speed_2x | 1.108 | 1.570 | 0.71x |
| effect fade_in | 1.353 | 2.297 | 0.59x |
| effect fade_out | 0.948 | 1.471 | 0.64x |
| effect flash_white | 1.687 | 1.955 | 0.86x |
| effect shake | 1.381 | 2.640 | 0.52x |
| effect zoom_in_center | 1.316 | 1.548 | 0.85x |
| effect chromatic_aberration | 4.146 | 4.281 | 0.97x |
| effect light_blur | 2.013 | 2.035 | 0.99x |
| effect moderate_blur | 2.044 | 1.969 | 1.04x |
| effect heavy_blur | 1.840 | 1.834 | 1.00x |
| effect light_sharpen | 1.753 | 2.141 | 0.82x |
| effect moderate_sharpen | 1.723 | 2.208 | 0.78x |
| effect heavy_sharpen | 1.748 | 2.459 | 0.71x |
| effect saturation_boost | 1.336 | 1.706 | 0.78x |
| effect heavy_saturation | 1.218 | 1.544 | 0.79x |
| effect desaturate | 1.456 | 1.486 | 0.98x |
| effect black_and_white | 0.999 | 1.566 | 0.64x |
| effect contrast_pop | 1.031 | 1.589 | 0.65x |
| effect warm_tint | 3.056 | 4.363 | 0.70x |
| effect cold_tint | 3.039 | 4.392 | 0.69x |
| effect vignette | 2.400 | 2.723 | 0.88x |
| effect bright_boost | 1.245 | 1.676 | 0.74x |
| effect dark_mood | 1.124 | 1.734 | 0.65x |
| effect invert_colors | 1.041 | 1.480 | 0.70x |
| effect text_highlight | 1.072 | 1.479 | 0.72x |
| effect text_fail | 0.962 | 1.573 | 0.61x |
| effect text_clutch | 1.038 | 1.500 | 0.69x |
| effect text_rip | 1.026 | 1.513 | 0.68x |
| effect text_nice | 0.991 | 1.513 | 0.66x |
| effect text_bruh | 0.957 | 1.449 | 0.66x |
| effect text_gg | 0.953 | 1.500 | 0.63x |
| effect text_lol | 0.973 | 1.622 | 0.60x |
| effect text_oof | 0.992 | 1.488 | 0.67x |
| effect light_grain | 1.167 | 3.108 | 0.38x |
| effect moderate_grain | 1.336 | 3.758 | 0.36x |
| effect heavy_grain | 1.673 | 4.937 | 0.34x |
| effect glitch | 2.641 | 5.734 | 0.46x |
| blur approximation | 1.900 | 1.463 | 1.30x |
| SFX decode cold/warm | 0.134 | <0.001 | 449.25x |
| proxy cold/warm | 0.960 | <0.001 | 2744.17x |
| SFX mix | 0.227 | 1.472 | 0.15x |
| transition | 1.056 | 2.157 | 0.49x |
| concat (no final encode) | 0.218 | 0.499 | 0.44x |
| intro/outro sequential/parallel | 1.273 | 0.863 | 1.47x |
| encoder legacy/preview | 0.865 | 1.313 | 0.66x |
| encoder legacy/final | 0.842 | 1.851 | 0.45x |
| end to end (2 clips) | 6.362 | 2.915 | 2.18x |

The two-clip montage improved **6.362 → 2.915 seconds (2.18×)** by combining
transitions/SFX/effects and running clips concurrently. Simple single-effect clips
usually regressed; grain-heavy clips regressed substantially. Do not adopt this
path as a universal speedup. Final's slower preset is a deliberate quality choice.
Copy concat also adds validation cost. Keep the old path available, prefer the
combined path for multi-stage montages, and benchmark longer real workloads before
changing production defaults. Both paths already have **zero separate final
video encodes**; the concat row measures final muxing.

The full benchmark ran on milestone `81ef0a5`. Subsequent safeguards reject
B-frame copy cuts, namespace repeated graph labels and validate positive thread
counts; they do not change this benchmark's workload. Expanded tests validate
those changes. No live Gemini calls were made and no key file was read.

Validation commands and exit codes:

* `bash tools/remote_run.sh "cd full_app && python -m pytest tests/test_perf.py -q"`:
  first run exit 1 (13 passed, 3 failed), exposing the legacy output-time speed
  semantics. Fixed by preserving legacy timing by default.
* `bash tools/remote_run.sh "cd full_app && python -m pytest tests/test_perf.py -q && python -m perf.bench --seconds 2 --effects --json /tmp/ext10-bench.json"`:
  exit 0; 16 tests passed, all effect and stage benchmarks completed, montage
  duration assertion passed.
* `bash tools/remote_run.sh "cd full_app && python -m pytest -q"`: exit 0;
  **22 passed in 13.54s**, including hardware fallback/timeout, cache invalidation
  and concurrent hits, output duration/streams/resolution, source-time speed,
  legacy nonzero cuts, repeated complex effects, silent input, copy eligibility
  and concat mismatch rejection. Synthetic media is generated inside the tests.

Remaining integration work belongs to the renderer owners: wire the opt-in adapter
into `services/ffmpeg_runner.py` or `render/`, normalize title outputs with the
same montage encoder settings, and validate actual GPU drivers/session limits.
Those paths are outside EXT-10's allowed paths. No application behavior changed.
