"""Deterministic product defaults and editorial enrichment; no provider calls."""
import copy


FULL_EXPERIENCE = dict(planner=True, profiles=True, use_signals=True, audio_ai=True,
    captions=True, reactions=True, sam=True, sam_reframe=True, music=True,
    beat_sync=True, transitions=True, cards=True, narration=True, social=True,
    privacy=False)


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
