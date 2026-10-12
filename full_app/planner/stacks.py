"""Seeded event-relevant stacks with hard adjacency and montage repeat limits."""
from collections import Counter
import math
import random
import re

from fx.catalog import catalog
from .models import Effect, Sound


def events_for(clip, source):
    s = source.signals
    events = [(e.kind, e.time) for e in s.events]
    if s.kill_time is not None:
        events.append(('headshot' if s.kind == 'headshot' else 'kill', s.kill_time))
    if s.fail_time is not None:
        events.append(('whiff' if s.kind == 'whiff' else 'death', s.fail_time))
    kind = 'clutch' if s.clutch else 'multikill' if s.multikill else s.kind
    kind = kind if kind in ('kill', 'headshot', 'multikill', 'clutch', 'death', 'whiff', 'ability') else ('fail' if source.label == 'lowlight' else 'play')
    events.append((kind, s.action_time if s.action_time is not None else (source.start+source.end)/2))
    for active, tag in ((s.clutch, 'clutch'), (s.multikill, 'multikill')):
        if active:
            events.append((tag, clip.source_start+(clip.peak-clip.start)*clip.speed))
    # Window descriptions can classify an existing anchor, never invent a kill time.
    description = source.caption.casefold()
    for pattern, tag in [(r'headshot', 'headshot'), (r'multi.kill|double kill|triple kill', 'multikill'),
                         (r'clutch', 'clutch'), (r'whiff|missed|misses', 'whiff'),
                         (r'ability|utility|ultimate|flash', 'ability'), (r'kill|elimination', 'kill')]:
        if re.search(pattern, description):
            events.append((tag, clip.source_start+(clip.peak-clip.start)*clip.speed))
    result = sorted(set((kind, clip.start+(time-clip.source_start)/clip.speed)
                        for kind, time in events if clip.source_start <= time < clip.source_end))
    return result or [(kind, clip.peak)]


def repeat_cap(count):
    # Scales for long montages while remaining <= roughly one in five clips.
    return max(2, math.ceil(count / 5))


def decorate_stacks(plan, sources):
    rng = random.Random(plan.seed)
    entries = list(catalog().values())
    counts, previous = Counter(), set()
    cap = repeat_cap(len(plan.clips))
    surprises = max(1, round(len(plan.clips)*plan.chaos*.4)) if plan.chaos else 0
    for c in plan.clips:
        events = events_for(c, sources[c.source_id])
        kinds = {k for k, _ in events}
        current = set()
        for group, minimum, maximum in [('vfx', 2, 4), ('sfx', 2, 5)]:
            if group == 'vfx' and c.speed == .5:
                maximum -= 1  # Count the existing slow-motion annotation.
            count = min(maximum, minimum + (1 if plan.mode == 'mean' else 0) +
                        sum(rng.random() < plan.chaos for _ in range(maximum-minimum)))
            for layer in range(count):
                candidates = [e for e in entries if e['kind'] == group and e['timing'] == 'event'
                              and (group, e['name']) not in previous | current
                              and counts[group, e['name']] < cap
                              and (plan.mode == 'mean' or e['mood'] != 'roast')]
                relevant = [e for e in candidates if kinds.intersection(e['events'])]
                wildcard = surprises > 0 and layer > 0 and rng.random() < plan.chaos*.2
                if wildcard:
                    surprises -= 1
                else:
                    candidates = relevant or candidates
                if group == 'vfx' and layer == 0:
                    core = {'hitmarker', 'zoom_punch', 'flash_white', 'shake', 'freeze', 'deep_fry'}
                    if plan.mode == 'mean' and sources[c.source_id].label == 'lowlight':
                        core = {'text_bruh', 'text_fail', 'text_rip', 'text_lol', 'text_oof'}
                    focused = [e for e in candidates if e['name'] in core]
                    candidates = focused or candidates
                if not candidates:
                    break
                target = (.8 if plan.mode == 'mean' else .45) + rng.uniform(-.15,.15)*plan.chaos
                weights = [(1 + 10*len(kinds.intersection(e['events']))/len(e['events'])) *
                           (1.1-abs(target-e['intensity'])) / (1+counts[group,e['name']]) for e in candidates]
                if plan.chaos:
                    chosen = rng.choices(candidates, weights=[w**(1/(.2+plan.chaos)) for w in weights])[0]
                else:
                    chosen = candidates[max(range(len(weights)), key=lambda i: weights[i])]
                anchors = [t for k,t in events if k in chosen['events']] or [c.peak]
                anchor = anchors[layer % len(anchors)]
                start = min(c.start+c.duration-min(.04,c.duration/2), max(c.start, anchor+rng.uniform(-.12,.12)*plan.chaos))
                duration = min(chosen['length'], c.start+c.duration-start)
                common = dict(clip_id=c.id, name=chosen['name'], start=start, duration=duration)
                if group == 'vfx':
                    plan.effects.append(Effect(**common))
                else:
                    gain = (.68 if plan.mode == 'mean' else .48) + rng.uniform(-.1,.1)*plan.chaos
                    plan.sfx.append(Sound(**common, gain=gain))
                current.add((group, chosen['name']))
                counts[group, chosen['name']] += 1
        previous = current
