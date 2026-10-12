"""Map local candidates to a common match clock and rank duplicate angles."""
import math
from collections.abc import Mapping

from .models import Angle, TeamCandidate, normalize
from .sync import probe, sync


def _get(candidate, key, default=None):
    return candidate.get(key, default) if isinstance(candidate, Mapping) else getattr(candidate, key, default)


def team_candidates(videos, candidates_per_video, *, offsets=None, overlap=.5) -> list[TeamCandidate]:
    """Group highlights sharing >= overlap of the shorter interval.

    Input candidates expose start/end and score (e.g. signals.Candidate or
    dictionaries). score is the caller's fused signals score. Explicit event_id
    values, when present on both candidates, must agree before grouping.
    """
    videos = normalize(videos)
    candidates_per_video = list(candidates_per_video)
    if len(videos) != len(candidates_per_video) or not 0 < overlap <= 1:
        raise ValueError("one candidate list per video and overlap in (0, 1] required")
    offsets = list(sync(videos) if offsets is None else offsets)
    if len(offsets) != len(videos):
        raise ValueError("one alignment per video required")
    items = []
    for index, (video, candidates, alignment) in enumerate(zip(videos, candidates_per_video, offsets)):
        duration, _ = probe(video.path)
        for candidate in candidates:
            start, end = float(_get(candidate, "start")), float(_get(candidate, "end"))
            score = float(_get(candidate, "score", 0))
            if not all(math.isfinite(v) for v in (start, end, score)) or not 0 <= start < end <= duration:
                raise ValueError("candidate must have finite score and timestamps inside its recording")
            items.append((Angle(index, alignment.to_match(start), alignment.to_match(end), score, video.player),
                          _get(candidate, "event_id")))
    groups = []
    for angle, event in sorted(items, key=lambda item: (item[0].start, item[0].video_index)):
        for group in groups:
            # Complete linkage avoids merging a chain of unrelated highlights;
            # never merge two independent candidates from the same recording.
            if all(a.video_index != angle.video_index and
                   (event is None or e is None or event == e) and
                   min(a.end, angle.end) - max(a.start, angle.start) >=
                   overlap * min(a.end - a.start, angle.end - angle.start) for a, e in group):
                group.append((angle, event))
                break
        else:
            groups.append([(angle, event)])
    result = []
    for group in groups:
        angles = tuple(sorted((a for a, _ in group), key=lambda a: (-a.score, a.video_index)))
        # Intersection is available in every angle, avoiding blank replay panels.
        result.append(TeamCandidate(max(a.start for a in angles), min(a.end for a in angles), angles))
    return sorted(result, key=lambda c: (c.start, c.end))
