"""Re-stack a saved v2 job without re-analysis, cut changes, or implicit API calls.

Service entry point for plan/render options: chaos, seed, optional configured refiner.
The HTTP options allowlist is owned by the pipeline task, not FX-2.
"""
from planner.models import RenderPlan, RankedClip
from planner.stacks import decorate_stacks, events_for
from planner.adapter import to_render_plan
from planner.refinement import refine_captions


def restack_saved_job(job, *, chaos=None, seed=0, refiner=None):
    data = dict(job['planner_plan'])
    data.update(chaos=(.6 if data['mode'] == 'mean' else .35) if chaos is None else chaos, seed=seed)
    plan = RenderPlan.model_validate(data)
    sources = {}
    originals = {str(c['id']): c for c in job.get('clips', [])}
    for clip in plan.clips:
        raw = originals.get(clip.source_id, {})
        start = raw.get('start_seconds', clip.source_start)
        end = raw.get('end_seconds', clip.source_end)
        evidence = raw.get('signals', {})
        signals = {k: evidence[k] for k in ('action_time','kill_time','fail_time')
                   if isinstance(evidence.get(k), (int,float)) and start <= evidence[k] < end}
        signals.update(clutch=evidence.get('clutch') is True or clip.similarity_key == 'clutch',
                       multikill=evidence.get('multikill') is True, kind=clip.similarity_key)
        signals['events'] = [dict(kind=e.get('type',e.get('kind')), time=e['time'])
                             for e in raw.get('events', [])
                             if e.get('type',e.get('kind')) in ('kill','headshot','multikill','clutch','death','whiff','ability')
                             and isinstance(e.get('time'),(int,float)) and start <= e['time'] < end]
        # Preserve DEMO-02's reviewed peak when no timestamp detector is available.
        signals.setdefault('action_time', clip.source_start+(clip.peak-clip.start)*clip.speed)
        sources[clip.source_id] = RankedClip(id=clip.source_id, start=start, end=end,
            score=clip.score, label=clip.label, signals=signals,
            caption=raw.get('caption',raw.get('description',''))[:240])
    plan.effects = [e for e in plan.effects if e.name == 'slow_motion']
    plan.sfx = []
    decorate_stacks(plan, sources)
    plan = RenderPlan.model_validate(plan.model_dump())
    events = {c.id: events_for(c,sources[c.source_id]) for c in plan.clips}
    if refiner is not None:
        plan = refine_captions(plan, refiner, events)
    return dict(planner_plan=plan.model_dump(mode='json'), edit_plan=to_render_plan(plan), events=events)
