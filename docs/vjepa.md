# V-JEPA 2 gameplay signals

This optional package freezes the video encoder, caches window embeddings, and trains
a three-class linear softmax probe (`none`, `kill`, `death`) plus a Bradley-Terry
pairwise linear ranker. Train a separate head for each game. The tiny seeded
random projection is a wiring-test encoder, not a useful gameplay model.

## Install and verify

From the repository root, with ffmpeg/ffprobe installed:

```bash
python -m pip install -e './full_app/vjepa[test]'
tools/remote_run.sh "pip install -q -e './full_app/vjepa[test]' && cd full_app && python -m pytest -q tests/test_vjepa.py"
```

Only NumPy is needed for cached features and probe training. Install the `hf` extra
for real extraction, and `modal` for the cloud scaffold:

```bash
python -m pip install -e './full_app/vjepa[hf,modal]'
```

Torch, transformers, torchvision and Modal are deliberately absent from the app's
base requirements. Importing `vjepa` does not import them. Disabled or missing-head
inference returns `[]`; missing optional Python dependencies log a warning and return
`[]`. Invalid heads, incompatible encoders, decode failures and game mismatches raise
errors rather than silently supplying misleading probabilities.

## Feature contract

```python
from vjepa.features import HFEncoder, WindowConfig, extract
encoder = HFEncoder(revision="YOUR_PINNED_HF_COMMIT", device="cuda")
data = extract("match.mp4", encoder, "workspace/vjepa-cache",
               WindowConfig(frames=32, fps=8, resolution=256, stride=2), batch_size=2)
```

The default checkpoint is `facebook/vjepa2-vitl-fpc64-256`. The wrapper runs
`get_vision_features` and mean-pools tokens; it does not run the prediction head.
The upstream [Transformers V-JEPA 2 API](https://huggingface.co/docs/transformers/en/model_doc/vjepa2)
documents the feature API and model configuration. Frame counts must be even,
16–64, and resolution a multiple of 16. Real checkpoints should start at 256 pixels;
alternate resolutions require validating the chosen checkpoint. CPU is supported
but the full encoder is large. Use a pinned revision for repeatable experiments.

Windows are half-open `[start,end)` seconds, sampled at configurable fps. Stride
cannot exceed window length, so inference has no gaps. The final short window is
included and repeat-padded with its last frame. ffmpeg decodes only pending windows;
memory is bounded by batch size, though repeated seeks can dominate long-video runs.
Frames are resized to a square (aspect ratio is not preserved). The processor does
normalization but no additional resizing, cropping or frame sampling.

Each compressed NPZ cache entry is keyed by SHA-256 of video bytes, window boundaries,
all sampling settings and encoder identity (including resolved HF commit). Cache
files contain only features, never pickle. Writes are atomic; corrupt entries are
recomputed. Content hashing streams the file once per extraction. Keep caches under
`workspace/`, outside git. Encoder implementation/preprocessing changes must bump
the `hf-mean-v1` identity version.

## Labels and dataset recipe

Collect your own gameplay recordings. Start with 20 hours and at least 20 distinct
matches per game; retain the original match ID across all cuts from that recording.
Aim for at least 500 audited kill and 500 death windows, plus comparable quiet and
high-motion negative windows. These are initial experiment targets, not accuracy
guarantees. Audit OCR actor attribution: a kill-feed entry about another player is
not automatically the player's kill.

| Game ID | Weak-label review focus | Ranking comparisons |
|---|---|---|
| `valorant` | Own-player kill feed, death, round boundaries | Multi-kill/clutch vs ordinary engagement |
| `overwatch2` | Elimination credit vs assists, respawn/death banners | Team fight turnaround vs routine damage |
| `deadlock` | Player kills/deaths vs NPC/creep events | Objective-saving fight vs farming |
| `league` | Champion kills/deaths vs minions/objectives | Outplay/team fight vs routine lane action |

Use `weak_labels(json_text_or_list_or_Path)` for Candidate dictionaries/Pydantic
objects. An envelope may contain `candidates` and `preferences`. Events accept
`type`/`kind` equal to `kill` or `death`, and absolute seconds in `time`, `timestamp`
or `start`. Other event kinds are ignored. Untimed kill/death strings or objects
label the whole candidate. Invalid/out-of-candidate timestamps are ignored.
Mixed kill/death windows use death precedence, deliberately losing multi-label detail.

Timestamped events are aligned only to feature windows containing the timestamp.
A no-event feature window is a weak `none` example only if a candidate fully covers
it; unannotated or partially covered negatives get `-1` and no classification loss.
OCR silence is noisy negative evidence, so review negatives before trusting metrics.

Make a JSON array of match records, with paths relative to the manifest:

```json
[
  {
    "match_id": "valorant-001",
    "game": "valorant",
    "video": "recordings/valorant-001.mp4",
    "candidates": [
      {"id": "clutch", "start": 10, "end": 16, "events": [{"type": "kill", "time": 13}], "decision": "keep"},
      {"id": "quiet", "start": 40, "end": 46, "events": [], "decision": "drop"},
      {"id": "death", "start": 70, "end": 76, "events": [{"type": "death", "time": 73}]}
    ],
    "preferences": [{"winner": "clutch", "loser": "quiet", "source": "gemini"}]
  }
]
```

Add at least one more **different match** before training. `source` is informational:
existing Gemini pair rankings are accepted, but this package never calls Gemini.
Normalize rankings into winner/loser candidate IDs. Keep/drop edits generate all
keep-over-drop comparisons within a record; duplicates are removed. For very large
edit histories, supply a sampled explicit preference list instead. Each candidate
maps to its highest-overlap feature window; pairs mapping to the same window or
outside the video are discarded. Review narrow candidates and sample at smaller
stride if too many pairs collapse.

```bash
cd full_app
python -m vjepa.train workspace/valorant.json workspace/valorant-head.npz \
  --device cuda --revision YOUR_PINNED_HF_COMMIT --batch-size 2 \
  --frames 32 --fps 8 --resolution 256 --stride 2 --epochs 300 --seed 13
```

Repeat with separate manifests/outputs for `overwatch2`, `deadlock`, and `league`.
For a wiring-only smoke test use `--tiny --resolution 32 --frames 16` on synthetic
videos; never promote that head to production.

The deterministic split holds out approximately 20% of match IDs (at least one).
Standardization and class-balanced classifier loss use training matches only;
ranking pairs never cross the split. Metrics printed as JSON and saved in the head
include per-class one-vs-rest AUROC, F1/support, macro F1, held-out ranking accuracy,
pair counts and match IDs. Missing positive/negative support yields null AUROC.
No ranking pairs yields `ranking_trained=false`, null ranking accuracy and zero
`sick_score`. Reject a model if held-out class support is inadequate, even when
macro F1 looks attractive. Maintain an additional untouched test set for final
selection; this scaffold supplies train/validation only. Softmax outputs trained
with balanced classes and ranker sigmoid scores are not calibrated probabilities
of real-world events or human approval.

## Modal extraction and CPU probe training

`vjepa/modal_app.py` is an undeployed, explicit-call factory. Put owned recordings
in a `lim-vjepa-data` Modal Volume using your normal Modal upload workflow. This
snippet starts billable work only when you run it; it was **not run** during EXT-13:

```python
from vjepa.modal_app import build_app
app, extract_match = build_app(gpu="L4")  # use "A100-80GB" for more memory
with app.run():
    print(extract_match.remote("recordings/valorant-001.mp4",
                               "features/valorant-001.npz",
                               "YOUR_PINNED_HF_COMMIT", batch_size=2))
```

The stub uses the default 32-frame, 8-fps, 256-pixel, two-second-stride config.
Begin with batch 1 if memory is constrained. Benchmark one match before a bulk
job. The mounted volume persists window caches and exported feature NPZs. Download
the exported NPZs, replace each manifest's `video` with a `features` path, and run:

```bash
python -m vjepa.train workspace/valorant-features.json workspace/valorant-head.npz \
  --precomputed --frames 32 --fps 8 --resolution 256 --stride 2
```

This trains on CPU with NumPy alone; no encoder or weight download is needed.
All feature artifacts must have identical encoder/configuration metadata. The
Modal export format is also easy to write locally with `atomic_npz`: arrays named
`features` and `windows`, and a JSON string `metadata` containing `encoder`, `config`
and `duration` from `extract()`.

## Planning cost, not a throughput benchmark

[Modal resource prices](https://modal.com/pricing), checked 2026-10-12, list L4 at
$0.000222/s (~$0.80/h) and A100 80GB at $0.000694/s (~$2.50/h). CPU and memory are
additional. Prices can change; check the linked page before scheduling.

At two-second stride, 20 video hours per game is approximately 36,000 windows;
four games produce approximately 144,000. Assume **unmeasured** sustained rates of
1–4 windows/s on L4 and 3–10 windows/s on A100, including decode. Then GPU-only costs
are:

| Dataset | L4 hours / cost | A100 80GB hours / cost |
|---|---|---|
| 20 hours, one game | 2.5–10 h / $2–$8 | 1–3.33 h / $2.50–$8.33 |
| 80 hours, four games | 10–40 h / $8–$32 | 4–13.33 h / $10–$33.33 |

Formula: `windows / measured_windows_per_second * price_per_second`. Reserve an
additional 30–100% for setup, cold starts, decoding stalls and retries, plus CPU,
RAM, storage and transfer. These assumptions can be wrong, especially on L4 with
large batches; measure warm throughput and peak memory on 100 windows first.
Doubling overlap roughly doubles cost. Full encoder fine-tuning is outside this
estimate. Probe training is CPU-only and reuses embeddings. At 1024 float32 values
per window, 144,000 raw embeddings take about 0.55 GiB before NPZ/filesystem overhead.

## Opt-in inference and fusion

```bash
export VJEPA_ENABLED=1
export VJEPA_HEAD=workspace/valorant-head.npz
export VJEPA_CACHE=workspace/vjepa-cache
```

```python
import vjepa
rows = vjepa.score("match.mp4", game="valorant", device="cuda")
# [{"second": 0, "kill_prob": 0.12, "sick_score": 0.71}, ...]
from vjepa.inference import fusion_signals
curves = fusion_signals("match.mp4", game="valorant", device="cuda")
# {"vjepa_kill": [...], "vjepa_sick": [...]} or {} when unavailable
```

Scores are overlap-weighted window averages for each `[second,second+1)` bucket,
including a final fractional second. No-event scoring does not imply a kill.
`fusion_signals(...)` returns optional curves; `signals.detect_candidates` does
not consume them automatically. No app route enables V-JEPA inference.
Actual gameplay quality, GPU memory/throughput, pretrained-HF execution and deployed
Modal behavior remain unverified; tests cover the offline scaffold and mocked HF
boundary only.
