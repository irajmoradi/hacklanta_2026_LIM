---
id: EXT-21
branch: ext/EXT-21
allowed_paths: [full_app/multipov/**, full_app/tests/**, docs/multipov.md]
---
# EXT-21: Multi-POV team montage
Build `full_app/multipov/`: combine recordings of the **same match** from several friends' POVs. Sync videos by **audio cross-correlation**
(game sound is shared; robust to voice chat differences) with drift correction; build a shared match timeline; when multiple POVs capture the same
highlight, pick the best angle (signals score) or do a split-screen / picture-in-picture replay ("from his POV…"); team montage mode that credits
each player (name tags). `multipov.sync(videos) -> offsets`, `multipov.team_candidates(videos, candidates_per_video)`. Tests: synthetic videos with a
shared audio track offset by known amounts (± seconds, plus slight speed drift) → recovered offsets within 1 frame; split-screen render valid.
Write docs/multipov.md.
