---
id: EXT-13
branch: ext/EXT-13
allowed_paths: [full_app/vjepa/**, full_app/tests/**, docs/vjepa.md]
---
# EXT-13: V-JEPA 2 signal plug-in (scaffolding; no big GPU spend)
Owner asked about training V-JEPA to detect kills / sick moments. Build `full_app/vjepa/` so it can be trained and used later:
- **Feature extraction:** wrap Meta V-JEPA 2 (HF `facebook/vjepa2-*` via transformers, optional extra) to embed sliding windows (16-64 frames at
  configurable fps/resolution) with batching and a disk cache (npz/parquet keyed by video hash + window). Support CPU for tiny tests and a
  Modal GPU function stub (`vjepa/modal_app.py`, not deployed) for real runs.
- **Weak labels:** `vjepa.weak_labels(candidates_json)` turns EXT-01 OCR kill/death events (Candidate.events) into positive/negative windows; also
  accept pairwise preference labels (keep/drop edits or Gemini pair rankings) for a "sick" ranking head.
- **Heads:** attentive-probe or logistic/MLP classifier for kill/death/none per game; a pairwise ranking head for "sick"; training script with
  train/val split by match, metrics (AUROC/F1), model save/load.
- **Inference as a signal:** `vjepa.score(video_path) -> per-second {kill_prob, sick_score}` in the same signals shape EXT-01 uses, plus a
  feature flag so fusion can add it when a trained head exists.
Tests use a **tiny random-init stand-in encoder** (no weight downloads) to verify windowing, caching, label alignment, training loop and
inference shapes. Write docs/vjepa.md with the exact recipe and cost estimate to train for Valorant/OW2/Deadlock/League (feature extraction on Modal L4/A100).
