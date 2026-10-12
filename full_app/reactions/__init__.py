"""Opt-in reaction overlays: instantiate a selector once per montage."""
from .pack import LABELS, Reaction, ReactionSelector, load_pack
from .render import render_overlay


def apply_reaction(base_clip, clip, selector, preset='landscape', *, enabled=False,
                   mode='nice', **render_options):
    """Backend hook after segment effects/speed changes, before concatenation.

    clip.peak_time is seconds in the final, speed-adjusted segment, not source time.
    """
    if not enabled:
        return base_clip
    reaction = selector.select(clip.get('label', ''), clip.get('score', 0.5), mode,
                               clip.get('suggested_reaction_label'))
    if reaction is None:
        return base_clip
    return render_overlay(base_clip, reaction, preset, peak_time=clip.get('peak_time'), **render_options)
