"""Normalize EXT-01/02 outputs and fuse independent candidate sources."""
from dataclasses import asdict, is_dataclass


def candidate_dict(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    return dict(value)


def overlap(a, b):
    return max(0, min(a['end_seconds'], b['end_seconds']) -
               max(a['start_seconds'], b['start_seconds']))


def rank_merge(candidates, scored, whole):
    assessments = {(c['start'], c['end']): c for c in scored}
    pool, vetoes = [], []
    for candidate in candidates:
        c = {**candidate, **assessments.get((candidate['start'], candidate['end']), {})}
        clip = dict(start_seconds=c['start'], end_seconds=c['end'],
                    score=min(1, max(0, c.get('score', 0))),
                    description=c.get('caption', 'Signal candidate'), type='good',
                    source='signals')
        if 'player_alive' in c:
            # Unknown viewpoint is unsafe to promote, just as in EXT-02.
            if c['player_alive'] is not True:
                vetoes.append(clip)
                continue
            if c['kind'] == 'neutral':
                continue
            clip.update(score=.35 * clip['score'] + .65 * c['hype'] / 10,
                        type='bad' if c['kind'] == 'lowlight' else 'good',
                        label=c['reaction'], suggested_reaction_label=c['reaction'],
                        source='signals+vlm')
        pool.append(clip)
    pool.extend({**c, 'score': c.get('score', .5), 'source': 'whole_video'} for c in whole)
    ranked = []
    for clip in sorted(pool, key=lambda c: (-c['score'], c['start_seconds'])):
        if any(overlap(clip, veto) > 0 for veto in vetoes):
            continue
        # Nonmaximum suppression retains complete beats without creating long unions.
        duplicate = next((old for old in ranked if overlap(clip, old) /
                          min(clip['end_seconds'] - clip['start_seconds'],
                              old['end_seconds'] - old['start_seconds']) >= .5), None)
        if duplicate is not None:
            duplicate['sources'] = sorted(set(duplicate.get('sources', [duplicate['source']]) + [clip['source']]))
        else:
            ranked.append(clip)
    for index, clip in enumerate(ranked):
        clip['id'] = str(index)
    return ranked[:500]
