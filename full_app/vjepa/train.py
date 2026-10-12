"""Train one game's probes from a JSON match manifest, holding out entire matches."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
from .features import HFEncoder, TinyEncoder, WindowConfig, extract
from .heads import Heads, match_split, metrics
from .labels import align_labels, weak_labels


def train(manifest, output, encoder, cache_dir, config=None, epochs=300, seed=13, batch_size=4):
    config = config or WindowConfig()
    games = {record["game"] for record in manifest}
    if len(games) != 1:
        raise ValueError("train exactly one game per head")
    xs, ys, matches, pairs = [], [], [], []
    offset = 0
    identity = encoder.identity if encoder is not None else None
    for record in manifest:
        if "features" in record:
            with np.load(record["features"], allow_pickle=False) as stored:
                extracted = {**json.loads(str(stored["metadata"])),
                             "features": stored["features"], "windows": stored["windows"]}
        else:
            if encoder is None:
                raise ValueError("precomputed training requires features for every match")
            extracted = extract(record["video"], encoder, cache_dir, config, batch_size)
        identity = identity or extracted["encoder"]
        if extracted["encoder"] != identity or extracted["config"] != asdict(config):
            raise ValueError("all features must share encoder and window configuration")
        labels = weak_labels({"candidates": record["candidates"], "preferences": record.get("preferences", [])})
        bounds = extracted["windows"]
        x = extracted["features"]
        if (x.ndim != 2 or bounds.shape != (len(x), 2) or not len(x) or
                not np.isfinite(x).all() or not np.isfinite(bounds).all() or
                (bounds[:, 0] < 0).any() or (bounds[:, 1] <= bounds[:, 0]).any()):
            raise ValueError("invalid precomputed features/windows")
        y = align_labels(bounds, labels)
        # Preference candidates map to the feature window with largest temporal overlap.
        mapping = {}
        for label in labels["windows"]:
            overlap = np.maximum(0, np.minimum(bounds[:, 1], label["end"]) - np.maximum(bounds[:, 0], label["start"]))
            if overlap.max() > 0:
                mapping[label["id"]] = offset + int(overlap.argmax())
        for winner, loser in labels["preferences"]:
            if winner in mapping and loser in mapping and mapping[winner] != mapping[loser]:
                pairs.append((mapping[winner], mapping[loser]))
        xs.append(x)
        ys.extend(y)
        matches.extend([str(record["match_id"])] * len(x))
        offset += len(x)
    x, y = np.concatenate(xs), np.asarray(ys)
    training, validation = match_split(matches, seed=seed)
    if not (y[validation] >= 0).any():
        raise ValueError("validation matches have no aligned labels")
    lookup = {int(global_index): local for local, global_index in enumerate(training)}
    train_pairs = [(lookup[a], lookup[b]) for a, b in pairs if a in lookup and b in lookup]
    head = Heads().fit(x[training], y[training], train_pairs, epochs=epochs)
    probabilities, scores = head.predict(x[validation])
    report = metrics(y[validation], probabilities)
    val_lookup = {int(index): local for local, index in enumerate(validation)}
    val_pairs = [(val_lookup[a], val_lookup[b]) for a, b in pairs if a in val_lookup and b in val_lookup]
    report["ranking_accuracy"] = (float(np.mean([scores[a] > scores[b] for a, b in val_pairs]))
                                  if val_pairs and head.ranking_trained else None)
    report["train_pairs"], report["validation_pairs"] = len(train_pairs), len(val_pairs)
    report["train_matches"] = sorted({matches[i] for i in training})
    report["validation_matches"] = sorted({matches[i] for i in validation})
    metadata = {"game": next(iter(games)), "encoder": identity, "config": extracted["config"],
                "metrics": report, "seed": seed}
    head.save(output, metadata)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", default="workspace/vjepa-cache")
    parser.add_argument("--model", default="facebook/vjepa2-vitl-fpc64-256")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--tiny", action="store_true", help="test stand-in; never use for production scoring")
    parser.add_argument("--precomputed", action="store_true", help="train from exported feature NPZs without loading an encoder")
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--fps", type=float, default=8)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--stride", type=float, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()
    encoder = None if args.precomputed else TinyEncoder() if args.tiny else HFEncoder(args.model, args.revision, args.device)
    records = json.loads(args.manifest.read_text())
    for record in records:
        for field in ("video", "features"):
            if field in record:
                record[field] = str(args.manifest.parent / record[field])
    report = train(records, args.output, encoder, args.cache,
                   WindowConfig(args.frames, args.fps, args.resolution, args.stride),
                   args.epochs, args.seed, args.batch_size)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
