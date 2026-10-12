"""Small NumPy softmax and Bradley-Terry linear ranking heads on frozen features."""
import json
import numpy as np
from .features import atomic_npz


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))


def _softmax(logits: np.ndarray) -> np.ndarray:
    probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
    return probabilities / probabilities.sum(axis=1, keepdims=True)


class Heads:
    def fit(self, x, y, pairs=(), epochs=300, learning_rate=0.05):
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=int)
        if (x.ndim != 2 or not len(x) or len(y) != len(x) or
                not np.isfinite(x).all() or not np.isin(y, [-1, 0, 1, 2]).all() or
                not (y >= 0).any() or epochs < 1 or learning_rate <= 0):
            raise ValueError("finite features, valid labels, and positive training parameters required")
        pairs = np.asarray(pairs, dtype=int).reshape(-1, 2)
        if pairs.size and (pairs.min() < 0 or pairs.max() >= len(x) or (pairs[:, 0] == pairs[:, 1]).any()):
            raise ValueError("invalid ranking pair indices")
        self.mean, self.scale = x.mean(axis=0), x.std(axis=0).clip(1e-6)
        z = (x - self.mean) / self.scale
        z = np.column_stack([z, np.ones(len(z))])
        self.classifier = np.zeros((z.shape[1], 3))
        self.ranker = np.zeros(z.shape[1])
        self.ranking_trained = bool(len(pairs))
        labeled = y >= 0
        target = np.eye(3)[y[labeled]]
        counts = np.bincount(y[labeled], minlength=3).clip(1)
        weights = 1 / counts[y[labeled]]
        weights /= weights.sum()
        labeled_features = z[labeled]
        differences = z[pairs[:, 0]] - z[pairs[:, 1]]
        for _ in range(epochs):
            probabilities = _softmax(labeled_features @ self.classifier)
            self.classifier -= learning_rate * (labeled_features.T @ ((probabilities - target) * weights[:, None]))
            if len(pairs):
                self.ranker += learning_rate * differences.T @ sigmoid(-differences @ self.ranker) / len(pairs)
        return self

    def predict(self, x):
        x = np.asarray(x, dtype=float)
        if x.ndim != 2 or x.shape[1] != len(self.mean) or not np.isfinite(x).all():
            raise ValueError("incompatible feature shape or nonfinite input")
        z = np.column_stack([(x - self.mean) / self.scale, np.ones(len(x))])
        probabilities = _softmax(z @ self.classifier)
        return probabilities, sigmoid(z @ self.ranker) if self.ranking_trained else np.zeros(len(x))

    def save(self, path, metadata):
        atomic_npz(path, mean=self.mean, scale=self.scale, classifier=self.classifier,
                   ranker=self.ranker, ranking_trained=self.ranking_trained,
                   metadata=json.dumps({**metadata, "schema": 1}))

    @classmethod
    def load(cls, path):
        head = cls()
        with np.load(path, allow_pickle=False) as data:
            metadata = json.loads(str(data["metadata"]))
            if metadata.get("schema") != 1:
                raise ValueError("unsupported head schema")
            for field in ("mean", "scale", "classifier", "ranker"):
                setattr(head, field, data[field])
            head.ranking_trained = bool(data["ranking_trained"])
        d = len(head.mean)
        if (head.mean.shape != (d,) or head.scale.shape != (d,) or
                head.classifier.shape != (d + 1, 3) or head.ranker.shape != (d + 1,) or
                not all(np.isfinite(getattr(head, name)).all() for name in ("mean", "scale", "classifier", "ranker")) or
                (head.scale <= 0).any()):
            raise ValueError("invalid saved head")
        return head, metadata


def match_split(matches, validation_fraction=0.2, seed=13):
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    groups = sorted(set(matches))
    if len(groups) < 2:
        raise ValueError("at least two distinct matches required")
    np.random.default_rng(seed).shuffle(groups)
    count = min(len(groups) - 1, max(1, round(len(groups) * validation_fraction)))
    validation = set(groups[:count])
    mask = np.asarray([match in validation for match in matches])
    return np.flatnonzero(~mask), np.flatnonzero(mask)


def metrics(y, probabilities):
    y, probabilities = np.asarray(y), np.asarray(probabilities)
    valid = y >= 0
    y, probabilities = y[valid], probabilities[valid]
    predicted = probabilities.argmax(axis=1)
    result = {}
    for index, name in enumerate(("none", "kill", "death")):
        positive = y == index
        tp = int(((predicted == index) & positive).sum())
        denominator = int((predicted == index).sum() + positive.sum())
        f1 = 2 * tp / denominator if denominator else 0.0
        # Mann-Whitney AUROC with average tie ranks, O(n log n) memory/time.
        scores = probabilities[:, index]
        order = np.argsort(scores, kind="stable")
        ranks = np.empty(len(scores), dtype=float)
        i = 0
        while i < len(order):
            j = i + 1
            while j < len(order) and scores[order[j]] == scores[order[i]]:
                j += 1
            ranks[order[i:j]] = (i + 1 + j) / 2
            i = j
        npos, nneg = int(positive.sum()), int((~positive).sum())
        auc = float((ranks[positive].sum() - npos * (npos + 1) / 2) / (npos * nneg)) if npos and nneg else None
        result[name] = {"f1": f1, "auroc": auc, "support": npos}
    return {"classes": result, "macro_f1": sum(row["f1"] for row in result.values()) / 3,
            "samples": len(y)}
