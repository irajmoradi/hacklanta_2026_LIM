"""Adapters for render v2, clip-local captions, reactions and SAM metadata."""
import copy
import os
from pathlib import Path
import shutil
import warnings

from services.ffmpeg_runner import FFmpegRunner
from services.probe import probe_video


def prepare_legacy(pipeline, job, plan, scratch):
    """Bake legacy time-changing effects before v2 framing/composition.

    Probe the actual encoded segments so caption/reaction/SAM clocks follow the
    resulting media, including legacy slow-motion effects and frame rounding.
    """
    runner = FFmpegRunner(scratch, Path(job['source']), job['meta']['width'],
                          job['meta']['height'], job['meta']['fps'])
    paths, segments, cursor = [], [], 0.
    with pipeline.stage(job, 'legacy_effects'):
        for index, segment in enumerate(plan['segments']):
            _, path = runner._render_one_segment(index, segment)
            duration = probe_video(path)['duration']
            paths.append(path)
            segments.append(dict(source_start=cursor, source_end=cursor + duration))
            cursor += duration
        source = runner.concatenate(paths)
        # Container duration may differ slightly from the summed segment clocks.
        segments[-1]['source_end'] = min(segments[-1]['source_end'], probe_video(source)['duration'])
    return source, dict(render_version=2, segments=segments)


def render_job(pipeline, job, key):
    options = job['options']
    renderer = pipeline.hook('render.engine', 'Renderer', job)
    # Legacy source-size output and thumbnail generation retain their old contract.
    if renderer is None:
        fallback = copy.deepcopy(job['edit_plan'])
        fallback.pop('render_version', None)
        pipeline.legacy_render(job, key, fallback)
        return
    if options.get('generate_thumbnails') or options.get('legacy_dimensions'):
        pipeline.legacy_render(job, key)
        return
    from render.plan import RenderPlan
    plan = copy.deepcopy(job['edit_plan'])
    original_segments = copy.deepcopy(plan['segments'])
    prepare = False
    if plan.get('render_version') != 2:
        unsupported = {'slow_motion', 'speed_2x', 'chromatic_aberration', 'fade_out'}
        if any(s.get('speed', 1) != 1 or unsupported.intersection(s.get('video_effects', [])) or
               s.get('transition_in', 'cut') != 'cut' for s in plan['segments']):
            prepare = True
        plan = dict(render_version=2, segments=[{k: v for k, v in s.items()
                    if k in {'source_start', 'source_end', 'video_effects', 'sound_effects', 'words', 'title', 'sam'}}
                    for s in plan['segments']])
    plan['preset'] = options.get('preset', plan.get('preset', 'landscape'))
    if options.get('captions'):
        plan['captions'] = {**plan.get('captions', {}), 'enabled': True, 'transcribe': True}
    elif 'captions' in options:
        plan['captions'] = {**plan.get('captions', {}), 'enabled': False}
    scratch = Path(job['dir']) / 'render_tmp'
    scratch.mkdir(exist_ok=True)
    try:
        source = Path(job['source'])
        if prepare:
            source, prepared = prepare_legacy(pipeline, job, job['edit_plan'], scratch)
            plan['segments'] = prepared['segments']
        with pipeline.stage(job, 'subject_track'):
            track = pipeline.hook('sam', 'subject_track', job) if options.get('sam_reframe') else None
            if track:
                for segment in plan['segments']:
                    start, end = segment['source_start'], segment['source_end']
                    points = track(source, start, end)
                    segment['sam'] = {'subject_track': [dict(time=max(0, t-start), x=x, y=y)
                                                       for t, x, y, *_ in points][::max(1, len(points)//499 + 1)]}
        validated = RenderPlan.model_validate(plan)
        pack = os.getenv('REACTION_PACK')
        selector, apply = None, None
        if options.get('reactions', bool(pack)):
            if pack:
                load = pipeline.hook('reactions', 'load_pack', job)
                factory = pipeline.hook('reactions', 'ReactionSelector', job)
                apply = pipeline.hook('reactions', 'apply_reaction', job)
                if load and factory and apply:
                    selector = factory(load(pack), seed=0)
            else:
                pipeline.warn(job, 'No REACTION_PACK configured; reactions disabled')
        spotlight = pipeline.hook('sam', 'render_effect', job) if options.get('sam') else None
        clips = job.get('clips') or []
        def metadata(segment):
            def overlap(c):
                return max(0, min(c['end_seconds'], segment.source_end) -
                           max(c['start_seconds'], segment.source_start))
            return max((c for c in clips if overlap(c)), key=overlap, default={})
        from types import SimpleNamespace
        clip_metadata = [metadata(SimpleNamespace(**s)) for s in original_segments]
        top = sorted(range(len(validated.segments)),
                     key=lambda i: clip_metadata[i].get('score', .5), reverse=True)[:3]

        def finish_segment(path, index, segment, duration, directory):
            if selector and apply:
                with pipeline.stage(job, f'reactions_{index}'):
                    path = apply(path, clip_metadata[index], selector, validated.preset,
                                 enabled=True, mode=options.get('mode', 'nice'))
            if spotlight and index in top:
                with pipeline.stage(job, f'spotlight_{index}'):
                    output = directory / f'spotlight_{index}.mp4'
                    spotlight(path, output, 0, duration, effect='spotlight_freeze', freeze_seconds=.6)
                    path = output
                    duration = probe_video(path)['duration']
            return path, duration

        runner = FFmpegRunner(scratch, source, *validated.size, validated.fps)
        with pipeline.stage(job, 'render_v2'), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', RuntimeWarning)
            output = renderer(runner, segment_processor=finish_segment).render(validated)
        if any('Automatic captions unavailable' in str(w.message) for w in caught):
            pipeline.warn(job, 'Automatic captions unavailable; install/cache faster-whisper or supply segment words')
        destination = Path(job['dir']) / 'output.mp4'
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError('Renderer produced no output')
        os.replace(output, destination)
        job['output'] = str(destination)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
