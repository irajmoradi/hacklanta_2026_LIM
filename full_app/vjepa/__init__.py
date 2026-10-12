"""Optional frozen V-JEPA features and gameplay probes. Imports stay dependency-free."""

from .labels import weak_labels


def score(video_path, **kwargs):
    """Return per-second signal dictionaries; disabled/missing extras return []."""
    from .inference import score as implementation
    return implementation(video_path, **kwargs)
