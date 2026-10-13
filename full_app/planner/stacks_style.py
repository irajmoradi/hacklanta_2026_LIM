"""Style boundaries applied after core decoration, before event stacks.

These policies govern editorial text, not optional speech transcription. Keeping
them here also makes saved-analysis restacks obey the same style contract.
"""
from .models import Effect, Sound, Text, Transition

CLEAN_VFX = frozenset(('light_sharpen', 'light_grain', 'vignette'))
CLEAN_SFX = ('impact_hit', 'cinematic_boom')
CINEMATIC_VFX = frozenset(('slow_motion', 'vignette', 'dark_mood', 'light_grain',
                           'warm_tint', 'cold_tint', 'black_and_white'))
CINEMATIC_SFX = ('cinematic_boom', 'prowler', 'death_note')


def restrained_stacks(plan, rng):
    """Return True when a restrained style completely owns its decoration."""
    if plan.style not in ('clean edit', 'cinematic'):
        return False
    cinematic = plan.style == 'cinematic'
    plan.effects = [e for e in plan.effects if cinematic and e.name == 'slow_motion']
    plan.sfx = []
    plan.text = []
    plan.reactions = []
    plan.transitions = []
    for i, clip in enumerate(plan.clips):
        whole = dict(clip_id=clip.id, start=clip.start, duration=clip.duration)
        climax = clip.phase in ('climax', 'hook_climax')
        if cinematic:
            grade = 'cold_tint' if clip.label == 'lowlight' or not climax else 'warm_tint'
            names = ['vignette', 'dark_mood', 'light_grain', grade]
            plan.transitions.append(Transition(**dict(whole, duration=min(.4, clip.duration)), name='fade_in'))
        else:
            names = [rng.choice(sorted(CLEAN_VFX)) if plan.chaos else 'light_sharpen']
        plan.effects.extend(Effect(**whole, name=name) for name in names)
        # One brief neutral title at the climax, never source descriptions or roasts.
        if climax:
            length = min(1.5, clip.duration)
            start = min(clip.peak, clip.start+clip.duration-length)
            plan.text.append(Text(clip_id=clip.id, start=start, duration=length,
                                  content='Final moment' if clip.label == 'lowlight' else 'Highlight'))
        progress = i / max(1, len(plan.clips)-1)
        sound = None
        if cinematic and (climax or (i > 0 and progress >= .5)):
            sound = 'cinematic_boom' if climax else (rng.choice(CINEMATIC_SFX[1:]) if plan.chaos else 'prowler')
        elif not cinematic and (climax or (len(plan.clips) > 3 and i == len(plan.clips)//2 and plan.chaos >= .5)):
            sound = rng.choice(CLEAN_SFX) if plan.chaos else CLEAN_SFX[0]
        if sound:
            start = min(clip.peak, clip.start+clip.duration-.04)
            plan.sfx.append(Sound(clip_id=clip.id, name=sound, start=start,
                                  duration=min(1.8 if cinematic else .6, clip.start+clip.duration-start),
                                  gain=.18+.32*progress if cinematic else .22))
    if plan.clips:
        last = plan.clips[-1]
        length = min(.75, last.duration/2)
        plan.transitions.append(Transition(clip_id=last.id, name='fade_out',
                                           start=plan.duration-length, duration=length))
    if cinematic:
        for point in plan.music.energy_curve:
            point.energy = .1 if point.time == plan.duration else .15+.75*point.time/max(plan.duration, 1)
    return True
