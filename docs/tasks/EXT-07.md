---
id: EXT-07
branch: ext/EXT-07
allowed_paths: [full_app/sam/**, full_app/tests/**, full_app/requirements*.txt, docs/sam.md]
---
# EXT-07: SAM-powered effects and reframing
Owner: "see if we can use SAM to make this better." Build `full_app/sam/` with a pluggable segmenter:
- Backends: (a) **SAM 3 via a remote HTTP endpoint** (configurable URL + key; text-prompted masks like "player character", "enemy", "weapon"), (b) **local SAM 2/2.1 small** via the `sam2` package if installed (optional extra), (c) a cheap fallback (motion/saliency mask) so everything works with no GPU.
- **Effects using masks:** (1) spotlight freeze: freeze-frame at the kill moment, subject cut out and outlined with a glow, background darkened/blurred, a text slam (SICK KILL), then resume; (2) subject outline/glow pulse; (3) background blur for vertical exports so the subject pops.
- **Reframe assist:** a per-frame subject track the vertical reframer can consume: `sam.subject_track(video, start, end) -> [(t, cx, cy, w, h)]`.
- Cache masks per clip; strict timeouts; never block the render if SAM fails (fall back).
Tests with synthetic videos using the fallback backend and a mocked remote backend: mask shape/size, effect render produces valid video of the right duration, track smoothness. Document setup (endpoint config, local SAM 2 install) and costs in docs/sam.md.
