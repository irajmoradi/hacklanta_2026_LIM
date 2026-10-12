"""360p draft render, using the existing performance renderer and proxy cache."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from render.plan import RenderPlan


class PreviewPlan(RenderPlan):
    resolution: Literal[360] = 360


def render_preview(job, plan, settings):
    from perf.cache import Cache
    from render.engine import Renderer
    from services.ffmpeg_runner import FFmpegRunner
    signature = hashlib.sha256(json.dumps([plan, settings], sort_keys=True).encode()).hexdigest()[:20]
    directory = Path(job['dir']) / 'agent_previews' / signature
    final = directory / 'final_edit.mp4'
    if final.is_file():
        return final
    draft = deepcopy(plan)
    draft.update(resolution=360, fps=15)
    draft.setdefault('captions', {})['transcribe'] = False
    if settings['music']:
        from music import pick_or_generate
        length = sum((s['source_end']-s['source_start'])/s.get('speed', 1) for s in draft['segments'])
        bed = pick_or_generate('chill' if job.get('options', {}).get('style') in ('clean_edit', 'cinematic') else 'energetic',
                               min(600, length), min(599, length*.8), output_dir=directory / 'music')
        draft['music'] = dict(path=str(bed.path), duck=True)
    validated = PreviewPlan.model_validate(draft)
    # The render engine works at 360p; proxy cache normalizes the final file.
    selector = None
    pack = os.getenv('REACTION_PACK')
    if settings['reactions'] and pack:
        from reactions import ReactionSelector, load_pack
        selector = ReactionSelector(load_pack(pack), seed=0)
    def reactions(path, index, segment, duration, scratch):
        from reactions import render_overlay
        for event in segment.reactions:
            reaction = selector.select(event.label, .5, job.get('options', {}).get('mode', 'nice'), event.label)
            if reaction:
                path = render_overlay(path, reaction, validated.preset, peak_time=event.start,
                    max_duration=event.duration, position=event.position,
                    duck_gain=.25 if event.duck_game_audio else 1)
        return path, duration
    runner = FFmpegRunner(directory, Path(job['source']), *validated.size, validated.fps, perf=True)
    output = Renderer(runner, segment_processor=reactions if selector else None).render(validated)
    return Cache(directory / 'proxy').proxy(output, height=360, fps=15)
