"""Version 1 adapter: planner v2 output clock -> renderer v2 clip-local clock."""
from .models import RenderPlan as PlannerPlan
from render.plan import RenderPlan

from render.contracts import ASPECT_PRESETS
ADAPTER_VERSION = 1


def to_render_plan(value):
    plan = PlannerPlan.model_validate(value.model_dump() if hasattr(value, 'model_dump') else value)
    if not plan.clips:
        raise ValueError('Cannot render an empty planner plan')
    segments = []
    for clip in plan.clips:
        def owned(group):
            return [p for p in group if p.clip_id == clip.id]
        def local(p):
            return dict(start=max(0, p.start-clip.start), duration=p.duration)
        effects = []
        for e in owned(plan.effects):
            if e.name == 'slow_motion' and clip.speed == .5:
                continue  # This is an annotation of the speed, not another slowdown.
            effects.append(dict(name=e.name, **local(e)))
        effects += [dict(name=t.name, **local(t)) for t in owned(plan.transitions) if t.name != 'cut']
        segments.append(dict(source_start=clip.source_start, source_end=clip.source_end,
            speed=clip.speed, timed_effects=effects,
            sound_effects=[dict(sfx_key=s.name, offset_in_segment=s.start-clip.start,
                                duration=s.duration, gain=s.gain) for s in owned(plan.sfx)],
            texts=[dict(content=t.content, position=t.position, **local(t)) for t in owned(plan.text)],
            reactions=[dict(label=r.label, position=r.position, duck_game_audio=r.duck_game_audio,
                            **local(r)) for r in owned(plan.reactions)]))
    return RenderPlan(segments=segments, preset=ASPECT_PRESETS[plan.aspect],
                      captions={'enabled': True}).model_dump(mode='json')
