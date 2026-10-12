---
id: EXT-10
branch: ext/EXT-10
allowed_paths: [full_app/perf/**, full_app/tests/**, docs/performance.md]
---
# EXT-10: Make rendering and effects fast
Owner: "Find ways to speed up the video and audio effects in the pipeline/rendering; it was pretty slow last time."
EXT-04 is rewriting the renderer in `full_app/render/` in parallel, so you build a **performance toolkit** in `full_app/perf/` that the
renderer and the old `services/ffmpeg_runner.py` can adopt, plus hard numbers:
1. **Profile the current pipeline** on the runner with synthetic 1080p60 gameplay-like clips (testsrc2 + noise + audio): time each stage of
   `services/ffmpeg_runner.py` (clip extraction, each effect, SFX mixing, concat, intro/outro, final encode). Record a baseline table.
2. **Speedups to implement as reusable helpers** (with before/after timings):
   - **Encoder selection:** detect NVENC / QSV / VAAPI / VideoToolbox and fall back to libx264 `-preset veryfast`/`superfast` + `-tune fastdecode`
     for previews and `faster` for finals; `-threads` tuned; avoid needless 2-pass.
   - **Fewer encodes:** cut with keyframe-aware stream copy where no effect applies; build **one filtergraph per clip** that applies all
     effects + text + SFX mix in a single encode instead of chained re-encodes; concat via the concat demuxer with identical codec params (no final re-encode).
   - **Parallelism:** render clips concurrently with a worker pool sized to cores (and GPU encoder session limits); render intro/outro in parallel.
   - **Cheaper effects:** downscale-first for blur/glow, `-filter_threads`/`-filter_complex_threads`, replace slow filters (e.g. `boxblur` vs `gblur`,
     precomputed overlays/PNG sequences, `zscale` vs `scale` where faster), cache rendered text/overlay assets.
   - **Audio:** pre-decode and resample SFX once to the target format (cache), mix with `amix`/`amerge` in the same graph, avoid per-effect audio re-encodes.
   - **Proxies:** low-res proxy files for analysis/preview; reuse decoded proxies across stages.
3. `perf.encoders.best()`, `perf.graph.single_pass(clip, effects, sfx, preset)`, `perf.parallel.render_all(jobs)`, `perf.cache` and a
   `python -m perf.bench` benchmark that prints the before/after table.
Tests: correctness (output duration/streams/resolution identical to the slow path within tolerance), encoder fallback logic, cache hits.
Write docs/performance.md with the measured numbers (baseline vs optimized per stage and end to end) and exact integration steps for
`services/ffmpeg_runner.py` and `render/`.
