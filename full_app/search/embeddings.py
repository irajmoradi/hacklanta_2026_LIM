"""Optional, explicitly enabled local sentence embeddings (no downloads)."""
import math


def normalized(values):
    vector = [float(value) for value in values]
    if not vector or not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding must be a finite nonempty vector")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Embedding must have a finite nonzero norm")
    return [value / norm for value in vector]


class LocalSentenceEncoder:
    """Load a pre-provisioned small model only when first used.

    Pin model_id to a model revision/path; changing it invalidates old vectors.
    Missing dependencies, weights, or runtime failures are handled by SearchIndex.
    """

    def __init__(self, model_id="sentence-transformers/all-MiniLM-L6-v2"):
        self.model_id = model_id
        self._model = None

    def encode(self, texts):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_id, local_files_only=True, device="cpu")
        return self._model.encode(texts, normalize_embeddings=True).tolist()
