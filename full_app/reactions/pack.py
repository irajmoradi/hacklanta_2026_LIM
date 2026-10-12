"""Local, validated reaction packs. No network or model dependencies."""
import json
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

LABELS = frozenset('sick_kill clutch bruh fail funny wholesome hype roast'.split())


@dataclass(frozen=True)
class Reaction:
    id: str
    speaker: str
    label: str
    text: str
    file: Path
    duration: float
    background: str


def load_pack(folder: str | Path) -> list[Reaction]:
    root = Path(folder).resolve()
    data = json.loads((root / 'pack.json').read_text(encoding='utf-8'))
    clips, ids = [], set()
    for entry in data['clips']:
        if any(not isinstance(entry.get(k), str) or not entry[k].strip()
               for k in ('id', 'speaker', 'label', 'file', 'background')):
            raise ValueError('Reaction identity, file and background must be nonempty strings')
        path = (root / entry['file']).resolve()
        duration = float(entry['duration'])
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Reaction file must exist inside the pack')
        if entry['id'] in ids or entry['label'] not in LABELS:
            raise ValueError('Duplicate id or unknown reaction label')
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Duration must be positive and finite')
        if entry['background'] not in ('light', 'transparent', 'opaque'):
            raise ValueError('Background must be light, transparent or opaque')
        if not isinstance(entry.get('text'), str):
            raise ValueError('Reaction text must be a string')
        clips.append(Reaction(**{**entry, 'file': path, 'duration': duration}))
        ids.add(entry['id'])
    return clips


class ReactionSelector:
    """Create one per montage/job; selection history is not shared between users."""
    def __init__(self, reactions: Iterable[Reaction], seed: int | None = None, cover_speakers: bool = False) -> None:
        self.reactions = list(reactions)
        self.rng = random.Random(seed)
        self.last_id = self.last_speaker = None
        self.counts: dict[str, int] = {}
        self.cover_speakers = cover_speakers
        self.speakers_seen = set()

    def select(self, label: str = '', score: float = 0.5, mode: str = 'nice',
               suggested_reaction_label: str | None = None) -> Reaction | None:
        if mode not in ('nice', 'mean'):
            raise ValueError('Mode must be nice or mean')
        candidates = [r for r in self.reactions
                      if (mode == 'mean' or r.label != 'roast') and r.id != self.last_id]
        if not candidates:
            return None  # Silence is preferable to repeating a singleton pack.
        preferred = suggested_reaction_label if suggested_reaction_label in LABELS else label
        if preferred not in LABELS:
            preferred = ('hype' if float(score) >= 0.7 else 'wholesome') if mode == 'nice' else 'roast'
        unseen = [r for r in candidates if r.speaker not in self.speakers_seen]
        if self.cover_speakers and unseen:
            candidates = unseen
        matching = [r for r in candidates if r.label == preferred]
        candidates = matching or candidates
        rotating = [r for r in candidates if r.speaker != self.last_speaker]
        candidates = rotating or candidates
        minimum = min(self.counts.get(r.id, 0) for r in candidates)
        chosen = self.rng.choice([r for r in candidates if self.counts.get(r.id, 0) == minimum])
        self.counts[chosen.id] = minimum + 1
        self.speakers_seen.add(chosen.speaker)
        self.last_id, self.last_speaker = chosen.id, chosen.speaker
        return chosen
