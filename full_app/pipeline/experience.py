"""Deterministic product defaults and editorial enrichment; no provider calls."""
import copy
import math

# Register the preset's new boolean with the shared HTTP validator. Keep this
# scoped here so FISH-1 does not edit FINAL-1's server validation files.
from server.validation import EXTENSION_FLAGS
EXTENSION_FLAGS.add('ai_cards')


FULL_EXPERIENCE = dict(planner=True, profiles=True, use_signals=True, audio_ai=True,
    captions=True, reactions=True, sam=True, sam_reframe=True, music=True,
    beat_sync=True, transitions=True, cards=True, narration=True, social=True,
    privacy=False, ai_cards=True, gemini_image=True, window_scoring=True)


def budget_duration(plan, maximum):
    """Reserve cards within the cap, trimming source and local events together.

    Work in whole frames; transitions and beat snapping only shorten this upper
    bound. Keep every selected clip when possible, with symmetric source trims.
    """
    plan = copy.deepcopy(plan)
    # Editorial captions are complete phrases; speech words remain untouched.
    for segment in plan['segments']:
        if 'texts' in segment:
            segment['texts'] = [t for t in segment['texts']
                               if len(t['content'].split()) > 1 and t['duration'] >= .75]
    if maximum is None:
        return plan
    fps = plan.get('fps', 30)
    frames = math.floor(maximum * fps + 1e-8)
    cards = [plan[k] for k in ('intro', 'outro') if plan.get(k)]
    # Tiny requests still retain gameplay and both cards (minimum 0.25 seconds).
    for card in cards:
        card['duration'] = max(math.ceil(.25*fps), min(round(card['duration']*fps),
                              frames // (len(cards)+1))) / fps
    available = frames - sum(round(c['duration']*fps) for c in cards)
    segments = plan['segments']
    # A transition requires a body plus two overlap frames.
    minimum = 3 if plan.get('transition', 'cut') != 'cut' else 1
    if available < minimum:
        raise ValueError('max_duration leaves no gameplay after cards')
    segments = segments[:max(1, available//minimum)]
    lengths = [(s['source_end']-s['source_start'])/s.get('speed', 1) for s in segments]
    counts = [max(1, round(d*fps)) for d in lengths]
    if sum(counts) > available:
        # Water-fill proportional allocations with a small per-clip floor.
        counts = [max(minimum, math.floor(available*d/sum(lengths))) for d in lengths]
        while sum(counts) > available:
            i = max(range(len(counts)), key=lambda i: counts[i])
            counts[i] -= 1
    for segment, old, count in zip(segments, lengths, counts):
        length = min(old, count/fps)
        offset = max(0., (old-length)/2)
        segment['source_start'] += offset*segment.get('speed', 1)
        segment['source_end'] = segment['source_start']+length*segment.get('speed', 1)
        trim_events(segment, offset, length, old)
    plan['segments'] = segments
    return plan


def trim_events(segment, offset, length, old):
    """Keep clip-local metadata inside the actual rendered interval."""
    for key in ('timed_effects', 'texts', 'reactions', 'sound_effects', 'words', 'fx'):
        kept = []
        for entry in segment.get(key, []):
            start_key = 'offset_in_segment' if key == 'sound_effects' else 'start'
            start = entry.get(start_key, 0)
            end = entry.get('end', start+(entry.get('duration') or old))
            left, right = max(0., start-offset), min(length, end-offset)
            if left >= right:
                continue
            if key == 'texts' and right-left < .75:
                continue
            entry[start_key] = left
            if key in ('words', 'fx'):
                entry['end'] = right
            else:
                entry['duration'] = right-left
            kept.append(entry)
        if key in segment:
            segment[key] = kept
    if segment.get('sam'):
        segment['sam']['subject_track'] = [dict(p, time=p['time']-offset)
            for p in segment['sam'].get('subject_track', []) if offset <= p['time'] <= offset+length]


def trim_beat_events(plan):
    """Mirror renderer timing so a snapped tail cannot leave invalid SFX/text."""
    from render.analysis import detect_beats, snap_durations
    from render.plan import RenderPlan
    validated = RenderPlan.model_validate(plan)
    if not validated.music or not validated.music.beat_sync:
        return plan
    fps = validated.fps
    durations = [max(1, round(s.duration*fps))/fps for s in validated.segments]
    cards = [round(c.duration*fps)/fps for c in (validated.intro, validated.outro) if c]
    overlap = (max(1, round(min(validated.transition_duration,
                   min(durations+cards)/3)*fps))/fps) if validated.transition != 'cut' else 0
    beats = validated.music.beats
    if beats is None:
        beats = detect_beats(validated.music.path, sum(durations+cards))
        plan['music']['beats'] = beats
    snapped = snap_durations(durations, beats, validated.music.snap_tolerance, overlap,
                             cards[0]-overlap if validated.intro else 0,
                             max(1/fps, 2*overlap+1/fps))
    for segment, old, duration in zip(plan['segments'], durations, snapped):
        trim_events(segment, 0, round(duration*fps)/fps, old)
    return plan


def enrich(job, plan):
    plan = copy.deepcopy(plan)
    options = job['options']
    if plan.get('render_version') != 2:
        return plan
    if options.get('transitions'):
        plan['transition'] = 'varied'
    if options.get('cards'):
        card_duration = min(1., max(.25, options.get('max_duration', 180)*.1))
        plan['intro'] = dict(text='BRUH MOMENTS' if options.get('mode') == 'mean' else 'MATCH HIGHLIGHTS', duration=card_duration)
        plan['outro'] = dict(text='GG - NEXT ROUND', duration=card_duration)
    if options.get('captions'):
        plan['captions'] = {'transcribe': True, **plan.get('captions', {}), 'enabled': True}
    if options.get('reactions'):
        previous_label = None
        for index, segment in enumerate(plan['segments']):
            length = (segment['source_end']-segment['source_start']) / segment.get('speed', 1)
            clips = [c for c in job.get('clips', []) if c['start_seconds'] < segment['source_end']
                     and c['end_seconds'] > segment['source_start']]
            clip = max(clips, key=lambda c: c.get('score', .5), default={})
            label = clip.get('suggested_reaction_label') or clip.get('reaction_label')
            if not label or label == previous_label:
                labels = ('bruh', 'fail', 'funny', 'roast') if options.get('mode') == 'mean' else ('sick_kill', 'hype', 'clutch', 'wholesome')
                choices = [value for value in labels if value != previous_label]
                label = choices[index % len(choices)]
            previous_label = label
            # One bounded event per selected clip, rather than a montage-wide cap.
            segment['reactions'] = [dict(start=length*.65, duration=min(1., length*.35), label=label)]
    return plan
