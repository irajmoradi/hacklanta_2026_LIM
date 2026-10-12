---
id: EVAL-02
branch: ext/EVAL-02
allowed_paths: [full_app/eval/**, docs/eval.md, docs/results.md]
---
# EVAL-02: Run the eval harness and publish numbers
Use `full_app/eval/` + `full_app/demo/make_demo_gameplay.py` to build a synthetic labelled benchmark (at least 6 videos, 2-4 min each, covering
Valorant/OW2/Deadlock/League-style HUD text and audio patterns, with death/spectating segments that must NOT be picked). Compare pipelines with a
**mocked VLM** (deterministic, noise-controlled stand-in so it is reproducible): signals-only, VLM-only (whole video), signals + window scoring
(REZE-style fusion), and fusion + audio AI + chat. Report precision/recall/F1 at IoU 0.3/0.5, ranking mAP, false picks during death/spectating,
time and estimated API cost per minute. Tune the fusion weights on half the set, report on the other half. Write docs/results.md with tables and
the tuned default weights (as a JSON the pipeline can load). Run on the runner.
