---
id: RENDER-FIX
branch: ext/RENDER-FIX
allowed_paths: [full_app/render/engine.py, full_app/render/graph.py, full_app/render/analysis.py, full_app/render/audio.py, full_app/render/plan.py, full_app/render/placements.py, full_app/render/contracts.py, full_app/perf/**, full_app/services/ffmpeg_runner.py, full_app/tests/test_render_v2.py, full_app/tests/test_render_fix*.py, full_app/tests/test_perf*.py, demo_video/renderfix/**, docs/rendering.md, docs/perf.md]
---
# RENDER-FIX: Landscape OOM, text-after-effects, and real render speed

From `docs/feature_audit.md` (AUDIT-2) gaps 2, 4 (render part) and 13:
1. **Full landscape fails** at the FFmpeg transition join under the worker's 8 GiB address-space limit (F62); the same plan renders outside
   the limit. Bound transition/xfade memory (chunked joins, intermediate encodes, lower-memory filters, no giant single filtergraph), test six
   segments plus intro/outro cards inside the same isolation limits. Errors from the renderer must carry a render category (not "Gemini").
2. **Composite text/word pops/banners after temporal effects** (freeze currently masks planned RIP text, F15/F17): order the graph so overlays
   and text render on top of freeze/slow/zoom; test.
3. **Speed** (F49; owner asked for faster rendering): Full rendering lost the promised speed: reaction processing makes segments sequential and
   captions/heads/narration add extra encodes. Parallelize isolated segment post-processing, consolidate passes (one encode per segment where
   possible: captions, reactions and overlays in the same graph), reuse the perf/ cache, and **measure** a matched Full-experience benchmark
   on an idle-ish runner (before/after wall time for the 60 s landscape + 30 s vertical from the saved DEMO-02 analysis on runner 1,
   `/srv/demo_out/demo02/`, privacy off, zero Gemini calls). Report the numbers honestly.
Full suite green on the runner. Other agents run in parallel (SAMFIX-1 reactions/sam, STYLE-1 fx/stacks, PARITY-UI server/pipeline/UI,
FISH-1 cards + pipeline/rendering.py, DEADLOCK-1 profiles/signals): stay in your paths; describe needed changes elsewhere in your report.
