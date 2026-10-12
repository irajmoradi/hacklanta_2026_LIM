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
                          job['meta']['height'], job['meta']['fps'], perf=job['options'].get('perf'))
    paths, segments, cursor = [], [], 0.
    with pipeline.stage(job, 'legacy_effects'):
        for index, segment in enumerate(plan['segments']):
            _, path = runner._render_one_segment(index, segment)
            duration = probe_video(path)['duration']
            paths.append(path)
            preserved = {k: copy.deepcopy(v) for k, v in segment.items()
                         if k in {'title', 'words', 'sam', 'fx'}}
            if 'caption' in segment:
                preserved['title'] = segment['caption']
            ratio = duration / (segment['source_end'] - segment['source_start'])
            for word in preserved.get('words', []):
                word['start'] *= ratio
                word['end'] *= ratio
            for point in (preserved.get('sam') or {}).get('subject_track', []):
                point['time'] *= ratio
            for effect in preserved.get('fx', []):
                effect['start'] *= ratio
                effect['end'] *= ratio
            segments.append(dict(source_start=cursor, source_end=cursor + duration, **preserved))
            cursor += duration
        source = runner.concatenate(paths)
        # Container duration may differ slightly from the summed segment clocks.
        segments[-1]['source_end'] = min(segments[-1]['source_end'], probe_video(source)['duration'])
    return source, dict(render_version=2, segments=segments)


def render_job(pipeline, job, key):
    from .extensions import private_source, finish_output, team_source
    scratch = Path(job['dir']) / 'extensions_tmp'
    scratch.mkdir(exist_ok=True)
    original = job['source']
    original_plan, original_meta = job['edit_plan'], job['meta']
    original_clips = job.get('clips')
    try:
        team = team_source(pipeline, job, scratch)
        if team:
            source, job['edit_plan'] = team
            job['source'] = str(source)
            job['meta'] = probe_video(source)
        elif job['options'].get('privacy', False):
            from .privacy_ranges import selected_source
            with pipeline.stage(job, 'privacy'):
                source, job['edit_plan'], job['clips'] = selected_source(pipeline, job, scratch)
                job['source'] = str(source)
                job['meta'] = probe_video(source)
        _render_job(pipeline, job, key)
        output = finish_output(pipeline, job, Path(job['output']), job['edit_plan'], scratch)
        destination = Path(job['dir']) / 'output.mp4'
        if output != destination:
            os.replace(output, destination)
        job['output'] = str(destination)
    finally:
        job['source'] = original
        job['clips'] = original_clips
        job['edit_plan'], job['meta'] = original_plan, original_meta
        shutil.rmtree(scratch, ignore_errors=True)


def _render_job(pipeline, job, key):
    options = job['options']
    for version_key in ('version', 'render_version'):
        if version_key in job['edit_plan'] and job['edit_plan'][version_key] != 2:
            raise ValueError(f'Unsupported {version_key}')
    renderer = pipeline.hook('render.engine', 'Renderer', job)
    # Legacy source-size output and thumbnail generation retain their old contract.
    if renderer is None or options.get('generate_thumbnails') or options.get('legacy_dimensions'):
        skipped = [name for name in ('cards', 'transitions', 'captions', 'music', 'reactions', 'sam', 'sam_reframe') if options.get(name)]
        if skipped:
            pipeline.warn(job, 'Legacy rendering cannot apply requested v2 features: ' + ', '.join(skipped))
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
    if 'clips' in plan and plan.get('version') == 2:
        from planner.adapter import to_render_plan
        plan = to_render_plan(plan)
    for segment in plan['segments']:
        if 'caption' in segment:
            segment['title'] = segment.pop('caption')
    original_segments = copy.deepcopy(plan['segments'])
    prepare = False
    if plan.get('render_version') != 2:
        unsupported = {'slow_motion', 'speed_2x', 'chromatic_aberration', 'fade_out'}
        if any(s.get('speed', 1) != 1 or unsupported.intersection(s.get('video_effects', [])) or
               s.get('transition_in', 'cut') != 'cut' for s in plan['segments']):
            prepare = True
        plan = dict(render_version=2, **{k: v for k, v in plan.items() if k in RenderPlan.model_fields and k not in ('render_version', 'segments')}, segments=[{k: v for k, v in s.items()
                    if k in {'source_start', 'source_end', 'video_effects', 'sound_effects', 'words', 'title', 'sam', 'fx'}}
                    for s in plan['segments']])
    from .experience import enrich
    if options.get('full_experience') and not job.get('_custom_plan'):
        plan = enrich(job, plan)
    plan['preset'] = options.get('preset', plan.get('preset', 'landscape'))
    if options.get('captions'):
        plan['captions'] = {'transcribe': True, **plan.get('captions', {}), 'enabled': True}
    elif 'captions' in options:
        plan['captions'] = {**plan.get('captions', {}), 'enabled': False}
    scratch = Path(job['dir']) / 'render_tmp'
    scratch.mkdir(exist_ok=True)
    try:
        source = Path(job['source'])
        if prepare:
            source, prepared = prepare_legacy(pipeline, job, job['edit_plan'], scratch)
            plan['segments'] = prepared['segments']
        if options.get('captions') is False:
            for segment in plan['segments']:
                segment.pop('title', None)
        if not options.get('fx') or not pipeline.hook('fx', 'compose', job):
            for segment in plan['segments']:
                segment.pop('fx', None)
        if options.get('music') and not plan.get('music'):
            generate = pipeline.hook('music', 'pick_or_generate', job)
            if generate:
                with pipeline.stage(job, 'music'):
                    length = sum((s['source_end']-s['source_start']) / s.get('speed', 1) for s in plan['segments'])
                    bed = generate(options.get('music_mood', 'chill' if options.get('style') in ('clean_edit', 'cinematic') else 'energetic'),
                                   min(600, length), min(599, length*.8), output_dir=scratch)
                    plan['music'] = dict(path=str(bed.path), beats=bed.beats, duck=True, beat_sync=options.get('beat_sync', True))
        applied_reactions, applied_sam = [], []
        with pipeline.stage(job, 'subject_track'):
            track = pipeline.hook('sam', 'subject_track', job) if options.get('sam_reframe') else None
            if track:
                for segment in plan['segments']:
                    start, end = segment['source_start'], segment['source_end']
                    with warnings.catch_warnings(record=True) as track_warnings:
                        warnings.simplefilter('always', RuntimeWarning)
                        points = track(source, start, end)
                    if track_warnings or not points:
                        pipeline.warn(job, 'SAM subject tracking unavailable or degraded; using fallback crop')
                    segment['sam'] = {**(segment.get('sam') or {}), 'subject_track': [dict(time=max(0, t-start)/segment.get('speed', 1), x=x, y=y)
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
                    try:
                        selector = factory(load(pack), seed=options.get('seed', 0), cover_speakers=True,
                                           clean=options.get('clean', False))
                    except (OSError, ValueError, KeyError):
                        pipeline.warn(job, 'REACTION_PACK unavailable or invalid; reactions skipped')
            else:
                pipeline.warn(job, 'No REACTION_PACK configured; reactions disabled')
        spotlight = pipeline.hook('sam', 'render_effect', job) if options.get('sam') else None
        if options.get('sam') or options.get('sam_reframe'):
            config_factory = pipeline.hook('sam', 'Config', job)
            if config_factory and config_factory.from_env().backend == 'fallback':
                pipeline.warn(job, 'SAM model unavailable: spotlight skipped; subject crop uses motion/contrast fallback')
                spotlight = None
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
            if spotlight and index in top:
                from sam import clip_masks
                masks = clip_masks(path, 0, duration)
                if masks.degraded:
                    pipeline.warn(job, 'SAM model failed or exhausted its budget; spotlight skipped')
                else:
                    with pipeline.stage(job, f'spotlight_{index}'):
                        output = directory / f'spotlight_{index}.mp4'
                        clip = clip_metadata[index]
                        peak = clip.get('signals', {}).get('kill_time', clip.get('peak_time'))
                        local_peak = ((peak-original_segments[index]['source_start']) / segment.speed
                                      if isinstance(peak, (float, int)) else duration/2)
                        local_peak = min(max(0, local_peak), max(0, duration-1/validated.fps))
                        spotlight(path, output, 0, duration, effect='spotlight',
                                  kill_time=local_peak, freeze_seconds=0)
                        # Duration-preserving spotlight keeps beats, captions and narration aligned.
                        path = output
                        applied_sam.append(dict(segment=index, time=local_peak, effect='spotlight'))
            if selector and apply and not segment.reactions and 'reactions' not in original_segments[index]:
                with pipeline.stage(job, f'reactions_{index}'):
                    path = apply(path, clip_metadata[index], selector, validated.preset,
                                 enabled=True, mode=options.get('mode', 'nice'),
                                 reaction_size=options.get('reaction_size', 'large'))
            if selector and segment.reactions:
                from reactions.render import render_overlay
                for event in segment.reactions:
                    reaction = selector.select(event.label, clip_metadata[index].get('score', .5),
                                               options.get('mode', 'nice'), event.label)
                    if reaction:
                        applied_reactions.append(dict(segment=index, id=reaction.id, speaker=reaction.speaker,
                                                      label=reaction.label, text=reaction.text, explicit=reaction.explicit,
                                                      start=min(event.start, max(0, duration-min(event.duration, reaction.duration))),
                                                      duration=min(event.duration, reaction.duration)))
                        with pipeline.stage(job, f'reactions_{index}'):
                            path = render_overlay(path, reaction, validated.preset, peak_time=event.start,
                                                  max_duration=event.duration, position=event.position,
                                                  reaction_size=options.get('reaction_size', 'large'),
                                                  duck_gain=.25 if event.duck_game_audio else 1)
            return path, duration

        runner = FFmpegRunner(scratch, source, *validated.size, validated.fps, perf=options.get('perf'))
        with pipeline.stage(job, 'render_v2'), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', RuntimeWarning)
            engine = renderer(runner, segment_processor=finish_segment if selector or spotlight else None)
            output = engine.render(validated)
            job['subtitle_events'] = getattr(engine, 'caption_events', [])
            executed = getattr(engine, 'executed_plan', validated)
            job['render_plan'] = executed.model_dump(mode='json')
            # Scratch music filenames must not be mistaken for reusable client assets.
            if job['render_plan'].get('music'):
                job['render_plan']['music']['path'] = 'generated music bed'
            job['render_evidence'] = dict(filter_graphs=getattr(engine, 'filter_graphs', []),
                timeline=getattr(engine, 'segment_timeline', []), reactions=applied_reactions, sam=applied_sam,
                privacy=bool(options.get('privacy', False)), output=probe_video(output))
            if options.get('reactions') and selector and not applied_reactions and all('reactions' in s for s in original_segments):
                pipeline.warn(job, 'Reactions requested but no eligible pack events were rendered')
        for warning in caught:
            pipeline.warn(job, str(warning.message))
        if any('Automatic captions unavailable' in str(w.message) for w in caught):
            pipeline.warn(job, 'Automatic captions unavailable; install/cache faster-whisper or supply segment words')
        destination = Path(job['dir']) / 'output.mp4'
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError('Renderer produced no output')
        os.replace(output, destination)
        job['output'] = str(destination)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
