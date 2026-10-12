"""Story selection and placement rules. No network, media, or model dependencies."""

from collections.abc import Iterable

from .models import (
    Effect, EnergyPoint, Music, PlannedClip, PlannerOptions, RankedClip,
    Reaction, RenderPlan, Sound, Text, Transition,
)


def _peak(clip: RankedClip) -> float:
    s = clip.signals
    for value in (s.action_time, s.fail_time if clip.label == "lowlight" else s.kill_time):
        if value is not None:
            return value
    return (clip.start + clip.end) / 2


def _kind(clip: RankedClip) -> str:
    s = clip.signals
    return s.kind.strip().casefold() or (
        "clutch" if s.clutch else "multikill" if s.multikill else
        "kill" if s.kill_time is not None else "fail" if clip.label == "lowlight" else "play"
    )


def _speed(clip: RankedClip, options: PlannerOptions) -> float:
    return 0.5 if clip.signals.clutch and options.style in ("hype montage", "cinematic") else 1.0


def _capacity(clip: RankedClip, options: PlannerOptions) -> float:
    return min(options.max_clip_length, (clip.end - clip.start) / _speed(clip, options))


def _rank(clip: RankedClip):
    # Keep measured scores intact; model-reviewed moments precede local fallbacks.
    return (-clip.validated, -clip.score, clip.id)


def _trim(clip: RankedClip, duration: float, speed: float) -> tuple[float, float]:
    span = duration * speed
    # Keep lead-in and some aftermath; clamp without ever leaving source bounds.
    start = max(clip.start, min(_peak(clip) - span * 0.65, clip.end - span))
    return start, start + span


def _decorate(plan: RenderPlan, sources: dict[str, RankedClip]) -> None:
    loud = plan.style in ("hype montage", "meme edit")
    cinematic = plan.style == "cinematic"
    for c in plan.clips:
        original = sources[c.source_id]
        end = c.start + c.duration

        def window(start, length):
            return dict(clip_id=c.id, start=start, duration=min(length, end - start))

        whole = window(c.start, c.duration)
        beat = window(c.peak, 1.5)
        if c.speed == 0.5:
            plan.effects.append(Effect(**whole, name="slow_motion"))
        if cinematic:
            plan.effects.append(Effect(**whole, name="vignette"))
        if loud and original.signals.kill_time is not None:
            kill = c.start + (original.signals.kill_time - c.source_start) / c.speed
            if c.start <= kill < end:
                hit = window(kill, 0.15)
                plan.effects.append(Effect(**hit, name="flash_white"))
                plan.sfx.append(Sound(**window(kill, 0.4), name="impact_hit"))
        if loud and original.signals.multikill:
            plan.effects.append(Effect(**window(c.peak, 0.4), name="zoom_in_center"))
        if original.label == "lowlight" and plan.mode == "mean":
            if loud:
                plan.effects.append(Effect(**beat, name="text_bruh"))
                plan.sfx.append(Sound(**window(c.peak, 0.8), name="spongebob_fail"))
            plan.text.append(Text(**beat, content="Confidence: 100. Accuracy: 0.", role="meme", position="center"))
        if original.caption:
            plan.text.append(Text(**whole, content=original.caption))
        # Teasers stay uncluttered. Slots refer to labels, never real avatar files.
        if c.phase != "hook" and (c.phase in ("climax", "hook_climax") or original.signals.clutch or original.signals.multikill):
            label = original.reaction_label or (
                "roast" if plan.mode == "mean" and c.label == "lowlight" else
                "clutch" if original.signals.clutch else "sick_kill" if original.signals.kill_time is not None else "hype"
            )
            if plan.mode == "nice" and label in ("roast", "bruh", "fail"):
                label = "wholesome"
            plan.reactions.append(Reaction(**beat, label=label,
                position="top_right" if plan.aspect == "9:16" else "bottom_right"))
        transition = "fade_in" if cinematic else "cut"
        if loud and c.phase == "climax":
            transition = "flash_white"
        plan.transitions.append(Transition(**window(c.start, 0.15 if transition == "flash_white" else min(0.4, c.duration)), name=transition))

    if not plan.clips:
        return
    last = plan.clips[-1]
    # Outro occupies the existing aftermath, so the top source remains last.
    tail = min(0.75, (plan.duration - last.peak) / 2)
    outro = dict(clip_id=last.id, start=plan.duration - tail, duration=tail)
    plan.text.append(Text(**outro, content="GG. Go next." if plan.mode == "mean" else "GG!", role="outro"))
    plan.transitions.append(Transition(**outro, name="fade_out"))
    points = []
    for i, c in enumerate(plan.clips):
        energy = 0.8 if i == 0 else 0.3 + 0.6 * i / max(1, len(plan.clips) - 1)
        points.append(EnergyPoint(time=c.start, energy=energy))
    points.extend([EnergyPoint(time=last.peak, energy=1), EnergyPoint(time=plan.duration, energy=0.1)])
    plan.music = Music(energy_curve=points, mood={
        "hype montage": "driving", "clean edit": "restrained",
        "meme edit": "playful", "cinematic": "dramatic",
    }[plan.style])


def plan_edit(
    clips: Iterable[RankedClip | dict], *, mode="nice", style="hype montage",
    target_length=30, aspect="16:9", min_clip_length=1, max_clip_length=6,
    refiner=None, fill_target=False,
) -> RenderPlan:
    """Plan a montage; a higher score means a stronger moment of either label.

    The hook repeats a teaser of the climax. All other source IDs occur once.
    An optional refiner receives a prompt and returns caption-only JSON patches.
    """
    options = PlannerOptions(mode=mode, style=style, target_length=target_length,
        aspect=aspect, min_clip_length=min_clip_length, max_clip_length=max_clip_length,
        fill_target=fill_target)
    # Revalidate models too: callers may have mutated an already validated input.
    ranked = [RankedClip.model_validate(c.model_dump() if isinstance(c, RankedClip) else c) for c in clips]
    sources = {c.id: c for c in ranked}
    if len(sources) != len(ranked):
        raise ValueError("ranked clip IDs must be unique")
    plan = RenderPlan(**options.model_dump(), duration=0)
    eligible = [c for c in ranked if _capacity(c, options) >= options.min_clip_length]
    preferred = [c for c in eligible if c.label == ("highlight" if mode == "nice" else "lowlight")]
    if not eligible:
        plan.notes.append("No clips meet the minimum output duration; returned an empty plan.")
        return plan
    if not preferred:
        plan.notes.append("Requested label unavailable; using the strongest available moment.")
        preferred = eligible
    # Stable tie break independent of the caller's list ordering.
    best = min(preferred, key=_rank)
    minimum = options.min_clip_length
    hook_duration = min(2, options.max_clip_length, best.end - best.start)
    hook_duration = max(minimum, hook_duration)
    # A slowed short source can qualify for the climax but not a normal-speed teaser.
    hook_speed = 1.0 if best.end - best.start >= hook_duration else _speed(best, options)
    schedule = []
    if options.target_length < hook_duration + minimum:
        schedule.append((best, "hook_climax", min(3, options.target_length, _capacity(best, options)), _speed(best, options)))
        plan.notes.append("Short budget: hook and climax share one clip; build-up omitted.")
    else:
        schedule.append((best, "hook", hook_duration, hook_speed))
        climax_duration = min(_capacity(best, options), options.target_length - hook_duration)
        remaining = options.target_length - hook_duration - climax_duration
        selected = []

        def ordered(items):
            return sorted(items, key=lambda item: (item[1] != "setup", item[0].validated, item[0].score, item[0].id))

        def varied(items):
            kinds = [_kind(best), *[_kind(item[0]) for item in ordered(items)], _kind(best)]
            return not any(a == b == c for a, b, c in zip(kinds, kinds[1:], kinds[2:]))

        # Prefer high scores for selection, then play them in ascending order.
        candidates = sorted((c for c in preferred if c.id != best.id), key=_rank)
        if mode == "mean":
            setups = sorted((c for c in eligible if c.label == "highlight" and c.id != best.id), key=_rank)
            for setup in setups:
                if remaining < minimum:
                    break
                duration = min(_capacity(setup, options), remaining, 3)
                item = (setup, "setup", duration, _speed(setup, options))
                if varied([item]):
                    selected.append(item)
                    remaining -= duration
                    break
        selected_ids = {item[0].id for item in selected}
        candidates = [c for c in candidates if c.id not in selected_ids]
        # Reconsider rejected candidates after a different kind creates space.
        while remaining >= minimum:
            for c in candidates:
                duration = min(_capacity(c, options), remaining)
                item = (c, "fail" if mode == "mean" else "highlight", duration, _speed(c, options))
                if varied([*selected, item]):
                    selected.append(item)
                    remaining -= duration
                    candidates.remove(c)
                    break
            else:
                break
        # If fails are scarce, use honest highlight context instead of inventing
        # more failures. Only lowlight-labelled sources receive roast decoration.
        if options.fill_target and mode == "mean":
            used = {best.id, *(item[0].id for item in selected), *(c.id for c in candidates)}
            candidates.extend(sorted((c for c in eligible if c.id not in used), key=_rank))
        # Variety is a preference in stock pipeline plans, not an eight-second cap.
        if options.fill_target and remaining >= minimum and candidates:
            plan.notes.append("Relaxed variety to fill the requested duration from ranked evidence.")
            for c in candidates:
                if remaining < minimum:
                    break
                duration = min(_capacity(c, options), remaining)
                selected.append((c, "fail" if c.label == "lowlight" and mode == "mean" else "highlight",
                                 duration, _speed(c, options)))
                remaining -= duration
        # Absorb a sub-minimum remainder without inventing another tiny clip.
        if options.fill_target and 0 < remaining < minimum:
            for i, (c, phase, duration, speed) in enumerate(selected):
                extra = min(remaining, _capacity(c, options) - duration)
                selected[i] = (c, phase, duration + extra, speed)
                remaining -= extra
        schedule.extend(ordered(selected))
        if mode == "nice" and len(schedule) > 1:
            c, _, duration, speed = schedule[1]
            schedule[1] = (c, "build_up", duration, speed)
        elif mode == "mean" and len(schedule) > 1 and schedule[1][1] != "setup":
            c, _, duration, speed = schedule[1]
            schedule[1] = (c, "setup", duration, speed)
        schedule.append((best, "climax", climax_duration, _speed(best, options)))
    cursor = 0.0
    for i, (clip, phase, duration, speed) in enumerate(schedule):
        start, end = _trim(clip, duration, speed)
        plan.clips.append(PlannedClip(id=f"clip_{i}", source_id=clip.id,
            source_start=start, source_end=end, start=cursor, duration=duration,
            speed=speed, phase=phase, score=clip.score, label=clip.label,
            similarity_key=_kind(clip), game_profile=clip.game_profile,
            peak=cursor + (_peak(clip) - start) / speed))
        cursor += duration
    plan.duration = cursor
    if cursor < options.target_length - 1e-6:
        plan.notes.append("Under budget: available footage, clip limits, or variety constraints limit duration.")
    if len(plan.clips) == 2:
        plan.notes.append("Only hook and climax fit; no distinct build-up/setup beat.")
    _decorate(plan, sources)
    plan = RenderPlan.model_validate(plan.model_dump())
    if refiner is not None:
        from .refinement import refine_captions
        plan = refine_captions(plan, refiner)
    return plan
