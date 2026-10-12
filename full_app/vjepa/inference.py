"""Opt-in fusion boundary. Disabled or unavailable probes contribute no signal."""
import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def score(video_path, *, enabled=None, head_path=None, game=None, encoder=None,
          cache_dir=None, device="cpu", batch_size=4):
    enabled = os.getenv("VJEPA_ENABLED", "0").lower() in ("1", "true", "yes") if enabled is None else enabled
    head_path = head_path or os.getenv("VJEPA_HEAD")
    if not enabled or not head_path or not Path(head_path).is_file():
        return []
    try:
        import numpy as np
        from .features import HFEncoder, WindowConfig, extract
        from .heads import Heads
        head, metadata = Heads.load(head_path)
        if game is not None and metadata["game"] != game:
            raise ValueError("head game does not match requested profile")
        if encoder is None:
            identity = metadata["encoder"]
            if not identity.startswith("hf-mean-v1:"):
                raise ValueError("test encoder must be supplied explicitly")
            model_id, revision = identity.removeprefix("hf-mean-v1:").rsplit("@", 1)
            encoder = HFEncoder(model_id, revision, device)
        if encoder.identity != metadata["encoder"]:
            raise ValueError("head and encoder fingerprints differ")
        data = extract(video_path, encoder, cache_dir or os.getenv("VJEPA_CACHE", "workspace/vjepa-cache"),
                       WindowConfig(**metadata["config"]), batch_size)
        probabilities, sick = head.predict(data["features"])
        result = []
        for second in range(math.ceil(data["duration"])):
            # Time-overlap weights also handle the final fractional second.
            weights = np.maximum(0, np.minimum(data["windows"][:, 1], min(second + 1, data["duration"])) -
                                 np.maximum(data["windows"][:, 0], second))
            if weights.sum() == 0:
                raise ValueError("window configuration left an uncovered second")
            result.append({"second": second, "kill_prob": float(np.average(probabilities[:, 1], weights=weights)),
                           "sick_score": float(np.average(sick, weights=weights))})
        return result
    except ImportError as exc:
        logger.warning("V-JEPA optional dependencies unavailable: %s", exc)
        return []


def fusion_signals(video_path, **kwargs):
    """Named per-second curves for EXT-01's normalization/weighted fusion stage."""
    rows = score(video_path, **kwargs)
    return ({"vjepa_kill": [row["kill_prob"] for row in rows],
             "vjepa_sick": [row["sick_score"] for row in rows]} if rows else {})
