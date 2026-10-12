---
id: EXT-18
branch: ext/EXT-18
allowed_paths: [full_app/fx/**, full_app/tests/**, docs/fx.md]
---
# EXT-18: FX engine v2: impact frames, speed ramps, shake
Build `full_app/fx/`: a library of modern montage effects as ffmpeg filter snippets (composable, used by the renderer through a small registry):
impact frame / flash-freeze on hits, **speed ramps** (fast → slow-mo around the kill → fast) with optional motion interpolation (`minterpolate`, and an
optional RIFE hook), zoom punch, screen shake, chromatic aberration, RGB split, VHS/CRT, motion blur trail, letterbox cinematic bars, color grades
(teal-orange, high-contrast, neon), kill-count counter overlay, freeze-frame with name tag. Each effect: params, cost estimate, a pure function
returning the filter string for given timing, and a preview renderer. Registry `fx.REGISTRY` with metadata the planner can choose from.
Tests: each effect renders a valid short video on a synthetic clip (duration preserved except speed ramps, which assert the expected new duration).
Write docs/fx.md with a contact sheet generator script.
