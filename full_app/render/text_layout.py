"""Conservative output-space reservations shared by planning and rendering.

Boxes are normalized and include outlines/motion. Unknown text filters reserve
the whole frame; omission is safer than guessing their font metrics. Intervals
are half open, so adjacent events do not collide.
"""
import re

INTERNAL = re.compile(r'\b(signal candidate|candidate \d+|unknown|untitled|placeholder|default caption)\b', re.I)


def editorial_text(value):
    value = ' '.join((value or '').split())
    return value if value and len(value.split()) <= 5 and not INTERNAL.search(value) else ''


def caption_box(preset):
    bottom = .80 if preset == 'vertical' else .90
    return (.08, bottom-.13, .92, bottom+.02)


def effect_box(name):
    if name.startswith('pop_'):
        return (0., .15, 1., .48)
    if name.startswith('banner_'):
        return (0., .15, 1., .43)
    if name == 'fail_arrow':
        return (0., .38, 1., .62)
    return (0., 0., 1., 1.)


def overlaps(a, b):
    return (a['start'] < b['end'] and b['start'] < a['end'] and
            a['box'][0] < b['box'][2] and b['box'][0] < a['box'][2] and
            a['box'][1] < b['box'][3] and b['box'][1] < a['box'][3])


def text_filter(name, fx=False):
    # Hit markers, particles and freeze arrows are gameplay graphics, not copy.
    if name.startswith('hitmarker') or name.endswith('_rain') or name in ('confetti_ace', 'freeze'):
        return False
    if fx:
        from fx import REGISTRY
        entry = REGISTRY.get(name)
        from fx import Timing
        return bool(entry and 'drawtext' in entry.filter(Timing(2., 0., 1.)))
    from models.effects import VIDEO_EFFECTS
    entry = VIDEO_EFFECTS.get(name, {})
    return entry.get('category') == 'text' or 'drawtext' in (entry.get('filter') or '')


def resolve_segment(segment, preset):
    """Mutate a private render plan, retaining higher-priority reservations.

    Reactions reserve their corner including pack subtitles. Speech precedes
    FX, which precede editorial captions/titles. Lower-priority collisions are
    omitted. The returned reservations are suitable for timeline regression QA.
    """
    boxes = []
    def admit(kind, start, end, box, content=''):
        item = dict(kind=kind, start=start, end=end, box=box, content=content)
        if any(overlaps(item, previous) for previous in boxes):
            return False
        boxes.append(item)
        return True

    # Pack sizes vary: reserve the entire right half, not just the face matte.
    reactions = []
    for r in segment.reactions:
        box = (.5, 0., 1., .5) if r.position == 'top_right' else (.5, .5, 1., 1.)
        if admit('reaction', r.start, r.start+r.duration, box):
            reactions.append(r)
    segment.reactions = reactions
    kept = []
    for w in segment.words:
        if admit('speech', w.start, w.end, caption_box(preset), w.text):
            kept.append(w)
    segment.words = kept
    segment.timed_effects = [e for e in segment.timed_effects if not text_filter(e.name) or
        admit('fx', e.start, e.start+e.duration, effect_box(e.name), e.name)]
    segment.video_effects = [e for e in segment.video_effects if not text_filter(e) or
        admit('fx', 0., segment.duration, effect_box(e), e)]
    segment.fx = [e for e in segment.fx if not text_filter(e['name'], True) or
        admit('fx', e['start'], e['end'], (0., 0., 1., 1.), e['name'])]
    kept = []
    for t in segment.texts:
        t.content = editorial_text(t.content)
        # Editorial text always uses the lower third; centre is for impact FX.
        t.position = 'lower_safe'
        if t.content and admit('caption', t.start, t.start+t.duration, caption_box(preset), t.content):
            kept.append(t)
    segment.texts = kept
    segment.title = editorial_text(segment.title) or None
    if segment.title and not admit('title', 0., min(3., segment.duration),
                                   (0., .03, 1., .30), segment.title):
        segment.title = None
    return boxes


def strip_descriptions(plan, descriptions):
    """Also protect saved plans, including short verbatim model descriptions."""
    descriptions = {' '.join(d.split()).casefold() for d in descriptions if d}
    for s in plan['segments']:
        for key in ('title', 'caption'):
            if ' '.join((s.get(key) or '').split()).casefold() in descriptions:
                s.pop(key, None)
        s['texts'] = [t for t in s.get('texts', [])
                      if ' '.join(t['content'].split()).casefold() not in descriptions]
    return plan
