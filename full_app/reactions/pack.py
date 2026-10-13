"""Local, validated reaction packs. No network or model dependencies."""
import json
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from contextvars import ContextVar

# The extension hook runs before the legacy renderer constructs its selector.
# Bind to its disposable render directory so failed/disabled renders cannot
# affect a later standalone selector. ContextVars isolate concurrent jobs.
_render_speakers = ContextVar('reaction_render_speakers', default=None)


def configure_render_speakers(speakers, scratch):
    _render_speakers.set((tuple(speakers), Path(scratch)))


def available_speakers():
    """Names from the configured, validated pack; never expose asset paths."""
    import os
    folder = os.getenv('REACTION_PACK')
    if not folder:
        return []
    try:
        return sorted({r.speaker for r in load_pack(folder)})
    except (OSError, ValueError, KeyError, TypeError):
        return []

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
    alpha_file: Path | None = None
    mask_file: Path | None = None
    explicit: bool = False
    style: str = ''


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
        if type(entry.get('explicit', False)) is not bool or not isinstance(entry.get('style', ''), str):
            raise ValueError('Invalid explicit/style reaction metadata')
        mattes = {}
        for key in ('alpha_file', 'mask_file'):
            value = entry.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Matte file must be a nonempty path')
            matte = (root / value).resolve()
            if not matte.is_relative_to(root) or not matte.is_file():
                raise ValueError('Matte file must exist inside the pack')
            mattes[key] = matte
        clips.append(Reaction(**{k: entry[k] for k in ('id', 'speaker', 'label', 'text', 'background')},
                              file=path, duration=duration, explicit=entry.get('explicit', False),
                              style=entry.get('style', ''), **mattes))
        ids.add(entry['id'])
    return clips


class ReactionSelector:
    """Create one per montage/job; selection history is not shared between users."""
    def __init__(self, reactions: Iterable[Reaction], seed: int | None = None, cover_speakers: bool = False, clean: bool = False,
                 reaction_speakers: Iterable[str] | None = None) -> None:
        pending = _render_speakers.get()
        _render_speakers.set(None)
        if reaction_speakers is None and pending and pending[1].is_dir():
            reaction_speakers = pending[0]
        selected = set(reaction_speakers or ())
        self.reactions = [r for r in reactions if not selected or r.speaker in selected]
        self.rng = random.Random(seed)
        self.last_id = self.last_speaker = None
        self.counts: dict[str, int] = {}
        self.cover_speakers = cover_speakers
        self.speakers_seen = set()
        self.clean = clean
        self.speaker_counts = {}

    def select(self, label: str = '', score: float = 0.5, mode: str = 'nice',
               suggested_reaction_label: str | None = None) -> Reaction | None:
        if mode not in ('nice', 'mean'):
            raise ValueError('Mode must be nice or mean')
        candidates = [r for r in self.reactions
                      if (mode == 'mean' or r.label != 'roast') and r.id != self.last_id
                      and not (self.clean and r.explicit)]
        if not candidates:
            return None  # Silence is preferable to repeating a singleton pack.
        if mode == 'nice':
            candidates = [r for r in candidates if not r.explicit] or candidates
        preferred = suggested_reaction_label if suggested_reaction_label in LABELS else label
        if preferred not in LABELS:
            preferred = ('hype' if float(score) >= 0.7 else 'wholesome') if mode == 'nice' else 'roast'
        unseen = [r for r in candidates if r.speaker not in self.speakers_seen]
        if self.cover_speakers and unseen:
            candidates = unseen
        elif self.cover_speakers:
            minimum = min(self.speaker_counts.get(r.speaker, 0) for r in candidates)
            candidates = [r for r in candidates if self.speaker_counts.get(r.speaker, 0) == minimum]
        matching = [r for r in candidates if r.label == preferred]
        candidates = matching or candidates
        rotating = [r for r in candidates if r.speaker != self.last_speaker]
        candidates = rotating or candidates
        minimum = min(self.counts.get(r.id, 0) for r in candidates)
        chosen = self.rng.choice([r for r in candidates if self.counts.get(r.id, 0) == minimum])
        self.counts[chosen.id] = minimum + 1
        self.speakers_seen.add(chosen.speaker)
        self.speaker_counts[chosen.speaker] = self.speaker_counts.get(chosen.speaker, 0) + 1
        self.last_id, self.last_speaker = chosen.id, chosen.speaker
        return chosen
