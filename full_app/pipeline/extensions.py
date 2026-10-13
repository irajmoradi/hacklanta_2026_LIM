"""Adapters for optional sprint modules; paid refinements/images require opt-in."""
import os
from pathlib import Path

from .ranking import candidate_dict


def analysis_inputs(pipeline, job, key=None):
    options = job['options']
    job['game'] = 'generic'
    job['_analysis_source'] = job['source']
    job['_chunks'] = []
    job['audio_signals'] = {}
    job['vjepa_signals'] = []
    job['profile_prompt'] = ''
    if options.get('profiles'):
        with pipeline.stage(job, 'profiles'):
            detect = pipeline.hook('profiles', 'detect_game', job)
            get = pipeline.hook('profiles', 'get_profile', job)
            if get:
                name = options.get('game', 'auto')
                if name == 'auto':
                    fallback = None
                    if os.getenv('GAME_DETECTION_VLM', '0') == '1':
                        def fallback(images):
                            with pipeline.client(job, key) as client:
                                return client.detect_game_frames(images)
                    name, confidence = detect(job['source'], vlm_fallback=fallback) if detect else ('generic', 0)
                    job['game_confidence'] = confidence
                else:
                    job['game_confidence'] = 1.0
                profile = get(name)
                job['game'] = profile.name
                job['profile_prompt'] = profile.prompt_fragment()
    if options.get('ingest'):
        with pipeline.stage(job, 'ingest'):
            prepare = pipeline.hook('ingest', 'prepare', job)
            if prepare:
                prepared = prepare(job['source'], cache_dir=Path(job['dir']) / 'ingest')
                job['_analysis_source'] = str(prepared.proxy)
                job['_chunks'] = [dict(path=str(c.path), start=c.start, end=c.end, index=i)
                                  for i, c in enumerate(prepared.chunks)]
    return job['_analysis_source']


def extra_signals(pipeline, job):
    """Add independent evidence before the shared VLM veto and NMS stage."""
    options, duration = job['options'], job['meta']['duration']
    rows = []
    if options.get('audio_ai'):
        with pipeline.stage(job, 'audio_ai'):
            analyze = pipeline.hook('audio_ai', 'analyze', job)
            if analyze:
                audio = candidate_dict(analyze(job['_analysis_source'], allow_model_downloads=False))
                job['audio_signals'] = audio
                for warning in audio.get('warnings', []):
                    pipeline.warn(job, warning)
                rows.extend(dict(start=e['start'], end=e['end'], score=e['score'],
                                 signals=e.get('signals', {}), events=[e])
                            for e in audio.get('events', []) if e['type'] != 'silence')
    if options.get('vjepa'):
        with pipeline.stage(job, 'vjepa'):
            score = pipeline.hook('vjepa', 'score', job)
            head = os.getenv('VJEPA_HEAD')
            if score and head and Path(head).is_file():
                try:
                    values = score(job['_analysis_source'], enabled=True, head_path=head,
                                   game=job['game'] if job['game'] != 'generic' else None,
                                   cache_dir=Path(job['dir']) / 'vjepa')
                except (ImportError, ValueError, OSError):
                    values = []
                job['vjepa_signals'] = values
                if not values:
                    pipeline.warn(job, 'V-JEPA produced no evidence; check optional dependencies and trained head')
                rows.extend(dict(start=r['second'], end=min(duration, r['second'] + 1),
                                 score=(r['kill_prob'] + r['sick_score']) / 2,
                                 signals={'vjepa_kill': r['kill_prob'], 'vjepa_sick': r['sick_score']})
                            for r in values if max(r['kill_prob'], r['sick_score']) >= .5)
            else:
                pipeline.warn(job, 'V-JEPA disabled: no trained VJEPA_HEAD available')
    if options.get('ingest') and options.get('chat'):
        chat_signal = pipeline.hook('ingest.chat', 'chat_signal', job)
        messages = [dict(offset=r['time'], message=' '.join(
            ['Kappa'] * min(100, int(r['emotes'])) + ['clip it'] * min(100, int(r['clip_it']))))
            for r in options['chat']]
        counts = {}
        for row in options['chat']:
            bucket = counts.setdefault(int(row['time']), dict(activity=0, emotes=0, clip_it=0))
            for name in bucket:
                bucket[name] += row[name]
        for r in chat_signal(messages, duration) if chat_signal else []:
            s = r['signals']
            # Keep the caller's original activity/emote counts in evidence;
            # the module computes normalized replay spikes from synthetic tokens.
            bucket = counts.get(int(r['start']), {})
            for name in ('activity', 'emotes', 'clip_it'):
                s['chat_' + name] = bucket.get(name, 0)
            if s['chat_clip_it'] or s['chat_emote_spike'] > 1:
                rows.append(dict(**r, score=min(1, .5 + .1 * s['chat_emote_spike'])))
    for r in rows:
        start, end = max(0, r['start'] - 1), min(duration, r['end'] + 1)
        if start < end:
            job['candidates'].append({**r, 'start': start, 'end': end})
    # Bound paid scoring work; retain the strongest local evidence.
    job['candidates'] = sorted(job['candidates'], key=lambda c: -c.get('score', 0))[:500]


def team_source(pipeline, job, scratch):
    """Compose aligned angles on each selected primary-source interval."""
    from reactions.pack import configure_render_speakers
    configure_render_speakers(job['options'].get('reaction_speakers', []), scratch)
    if not job['options'].get('multipov'):
        return None
    sources = job.get('sources', [job['source']])
    if len(sources) < 2:
        pipeline.warn(job, 'Team mode requires multiple video uploads; using primary POV')
        return None
    sync = pipeline.hook('multipov', 'sync', job)
    render = pipeline.hook('multipov', 'render_montage', job)
    if not sync or not render:
        return None
    from multipov import Video, TeamCandidate, Angle, SyncError, team_candidates
    from services.probe import probe_video
    from services.ffmpeg_runner import FFmpegRunner
    from dataclasses import asdict
    with pipeline.stage(job, 'multipov'):
        videos = [Video(path, f'Player {i+1}') for i, path in enumerate(sources)]
        try:
            offsets = sync(videos)
        except SyncError:
            pipeline.warn(job, 'Team audio could not be aligned; using primary POV')
            return None
        durations = [probe_video(v.path)['duration'] for v in videos]
        detect = pipeline.hook('signals', 'detect_candidates', job)
        evidence = [[candidate_dict(c) for c in detect(v.path)] if detect else [] for v in videos]
        # Each selected local range is sanitized below before composition.
        per_video = [[] for _ in videos]
        paths, segments, cursor = [], [], 0.
        width, height = job['meta']['width'], job['meta']['height']
        width, height = max(320, width//4*4), max(180, height//4*4)
        for index, segment in enumerate(job['edit_plan']['segments']):
            start, end = segment['source_start'], segment['source_end']
            angles = []
            for i, alignment in enumerate(offsets):
                local_start, local_end = alignment.to_local(start), alignment.to_local(end)
                if 0 <= local_start < local_end <= durations[i]:
                    score = max((c.get('score', .5) for c in evidence[i]
                                 if c['start'] < local_end and c['end'] > local_start), default=.5)
                    per_video[i].append(dict(start=local_start, end=local_end, score=score, event_id=str(index)))
                    angles.append(Angle(i, start, end, score, videos[i].player))
            angles.sort(key=lambda a: (-a.score, a.video_index))
            render_videos, render_offsets = list(videos), list(offsets)
            if job['options'].get('privacy', False):
                from .privacy_ranges import private_range
                from multipov import Alignment
                for angle in angles[:1 if job['options'].get('team_mode', 'best') == 'best' else 2]:
                    i = angle.video_index
                    local_start, local_end = offsets[i].to_local(start), offsets[i].to_local(end)
                    private = private_range(pipeline, job, videos[i].path, local_start, local_end, scratch)
                    render_videos[i] = Video(private, videos[i].player)
                    render_offsets[i] = Alignment(start, offsets[i].rate, offsets[i].confidence)
            path = render(render_videos, [TeamCandidate(start, end, tuple(angles))],
                          scratch / f'team_{index}.mp4', offsets=render_offsets,
                          mode=job['options'].get('team_mode', 'best'), width=width, height=height,
                          fps=job['meta']['fps'])
            length = probe_video(path)['duration']
            segments.append({**segment, 'source_start': cursor, 'source_end': cursor+length})
            paths.append(path)
            cursor += length
        job['team_candidates'] = [asdict(c) for c in team_candidates(videos, per_video, offsets=offsets)]
        job['team_alignments'] = [asdict(a) for a in offsets]
        source = FFmpegRunner(scratch, videos[0].path, width, height, job['meta']['fps']).concatenate(paths)
        segments[-1]['source_end'] = min(segments[-1]['source_end'], probe_video(source)['duration'])
        return source, {**job['edit_plan'], 'segments': segments}


def planner_plan(pipeline, job, key=None):
    plan_edit = pipeline.hook('planner', 'plan_edit', job)
    if not plan_edit:
        return None
    from render.contracts import ASPECT_PRESETS, STYLE_IDS
    options = job['options']
    clips = []
    for c in job['clips']:
        if not c.get('keep', True):
            continue
        if options.get('mode', 'nice') == 'nice' and c.get('nice_veto'):
            continue
        evidence = c.get('signals', {})
        reaction = c.get('suggested_reaction_label', c.get('reaction_label', c.get('label')))
        signals = dict(clutch=evidence.get('clutch') is True or reaction == 'clutch',
                       multikill=evidence.get('multikill') is True)
        kinds = {'kill', 'headshot', 'multikill', 'clutch', 'death', 'whiff', 'ability', 'play'}
        signals['events'] = []
        for event in [*evidence.get('events', []), *c.get('events', [])]:
            kind, time = event.get('kind', event.get('type')), event.get('time')
            normalized = dict(kind=kind, time=time)
            if (kind in kinds and type(time) in (int, float)
                    and c['start_seconds'] <= time < c['end_seconds']
                    and normalized not in signals['events']):
                signals['events'].append(normalized)
        for name in ('action_time', 'kill_time', 'fail_time'):
            value = evidence.get(name)
            if isinstance(value, (float, int)) and c['start_seconds'] <= value < c['end_seconds']:
                signals[name] = value
        # Detector event anchors give the trim a real pre-roll and aftermath.
        explicit_action = signals.get('action_time') is not None
        audio_beats = []
        for event in c.get('events', []):
            time = event.get('time')
            if isinstance(time, (float, int)) and c['start_seconds'] <= time < c['end_seconds']:
                kind = event.get('type')
                if kind in ('kill', 'death'):
                    signals.setdefault('kill_time' if kind == 'kill' else 'fail_time', time)
                elif kind == 'sustained_audio':
                    end = min(c['end_seconds'], event.get('end', time))
                    if end > time:
                        audio_beats.append((end-time, (time+end)/2))
        if not explicit_action:
            event_peak = signals.get('fail_time' if c.get('type') == 'bad' else 'kill_time')
            if event_peak is None and audio_beats:
                center = (c['start_seconds'] + c['end_seconds']) / 2
                event_peak = max(audio_beats, key=lambda beat: (beat[0], -abs(beat[1]-center)))[1]
            if event_peak is not None:
                signals['action_time'] = event_peak
        clips.append(dict(id=c['id'], start=c['start_seconds'], end=c['end_seconds'],
                          validated=(c.get('editorial_review') is True or
                                     c.get('source') in ('signals+vlm', 'whole_video') and not c.get('nice_veto', False)),
                          score=c.get('score', .5), label='lowlight' if c.get('type') == 'bad' else 'highlight',
                          caption=c.get('caption', c.get('description', ''))[:240],
                          signals=signals, game_profile=job.get('game', 'generic')))
    if not clips:
        raise ValueError('No eligible clips for this mode')
    target = options.get('max_duration', 30 if options.get('preset') == 'vertical' else 60)
    if options.get('cards'):
        target = max(.5, target - 2*min(1., max(.25, target*.1)))
    result = plan_edit(clips, mode=options.get('mode', 'nice'),
                       chaos=options.get('chaos', .6 if options.get('mode') == 'mean' else .35),
                       seed=options.get('seed', 0),
                       style={v: k for k, v in STYLE_IDS.items()}[options.get('style', 'hype_montage')],
                       target_length=target,
                       fill_target=True, max_clip_length=10,
                       min_clip_length=min(1, min(c['end']-c['start'] for c in clips)),
                       aspect={v: k for k, v in ASPECT_PRESETS.items()}[options.get('preset', 'landscape')])
    if options.get('plan_refinement'):
        from planner.refinement import Refinement, refine_captions
        from planner.models import RenderPlan
        from services.gemini_client import GeminiVideoClient
        from services.call_budget import CallBudget
        client = None
        try:
            client = GeminiVideoClient(api_key=key)
            client.budget = CallBudget(Path(job['dir']) / 'gemini-budget.sqlite3')
            def refine(prompt):
                return client._generate([prompt + '\nEditing instructions:\n' +
                    options.get('editing_instructions', '')], Refinement).model_dump()
            result = refine_captions(RenderPlan.model_validate(candidate_dict(result)), refine)
        except Exception:
            pipeline.warn(job, 'Plan refinement unavailable; deterministic draft retained')
        finally:
            if client is not None:
                client.close()
    native = candidate_dict(result)
    job['planner_plan'] = native
    job['seed'] = native['seed']
    if not native['clips']:
        pipeline.warn(job, 'Planner produced no eligible clips; using legacy planner')
        return None
    from planner.adapter import to_render_plan
    adapted = to_render_plan(native)
    if options.get('captions'):
        adapted['captions']['transcribe'] = True
    if options.get('fx'):
        catalog = pipeline.hook('fx', 'metadata', job)
        if catalog and 'zoom_punch' in catalog():
            for segment in adapted['segments']:
                length = (segment['source_end']-segment['source_start']) / segment['speed']
                segment['fx'] = [dict(name='zoom_punch', start=length*.4, end=length*.6, params={})]
    return adapted


def private_source(pipeline, job, source, scratch, suffix=''):
    if not job['options'].get('privacy', False):
        return source
    sanitize = pipeline.hook('privacy', 'sanitize', job)
    if not sanitize:
        return source
    with pipeline.stage(job, 'privacy' + suffix):
        payload = dict(job['options'].get('privacy_options', {}))
        payload.setdefault('game', job.get('game', 'generic'))
        payload.setdefault('backend', 'none')
        if payload.get('regions') is None:
            from privacy import PrivacyOptions
            from privacy.profiles import regions_for
            regions = regions_for(PrivacyOptions.model_validate(payload))
            allowed = {'kill_feed', 'chat', 'party_voice'}
            if payload.get('blur_webcam'): allowed.add('webcam')
            payload['regions'] = {k: v.model_dump() for k, v in regions.items() if k in allowed}
        path, track = sanitize(source, scratch / f'private{suffix}.mp4', payload)
        job['privacy_track' + suffix] = track.model_dump(mode='json')
        for warning in track.warnings:
            pipeline.warn(job, warning)
        return path


def finish_output(pipeline, job, output, plan, scratch):
    # A rerender starts with fresh audio; never report a previous narrator track.
    job.pop('narration_track', None)
    job.get('render_evidence', {}).pop('narration_graph', None)
    job.get('timings', {}).pop('narration', None)
    if job['options'].get('narration'):
        build = pipeline.hook('narration', 'build', job)
        render = pipeline.hook('narration.render', 'render', job)
        if build and render:
            with pipeline.stage(job, 'narration'):
                narration_plan = {**plan, 'segments': [dict(s) for s in plan['segments']]}
                evidence = job.get('render_evidence', {})
                for segment, timing in zip(narration_plan['segments'], evidence.get('timeline', [])):
                    segment.update(output_start=timing['start'], output_duration=timing['duration'])
                narration_plan['reaction_overlays'] = [dict(start=evidence['timeline'][r['segment']]['start']+r['start'],
                    end=evidence['timeline'][r['segment']]['start']+r['start']+r['duration']) for r in evidence.get('reactions', [])]
                track = build(job.get('clips') or [], narration_plan, cache_dir=Path(job['dir']) / 'narration',
                              persona=job['options'].get('narration_persona', 'deadpan_roast' if job['options'].get('mode') == 'mean' else 'hype_caster'),
                              allow_network=False, local_voice=True)
                if not any(s.audio_file for s in track.segments):
                    pipeline.warn(job, 'Narration requested but no audio fit the available speech gaps')
                from services.probe import probe_video
                track.duration = probe_video(output)['duration']
                for warning in track.warnings:
                    pipeline.warn(job, warning)
                job['narration_track'] = [dict(start=s.start, end=s.end, text=s.text,
                                               has_audio=s.audio_file is not None) for s in track.segments]
                from narration import filter_graph
                job.setdefault('render_evidence', {})['narration_graph'] = filter_graph(track)
                output = render(output, track, scratch / 'narrated.mp4')
    if job['options'].get('social'):
        build = pipeline.hook('social', 'build_share_kit', job)
        if build:
            import shutil
            with pipeline.stage(job, 'social'):
                export = scratch / 'export'
                export.mkdir(exist_ok=True)
                shutil.copyfile(output, export / 'final_edit.mp4')
                share_plan = {**plan, 'captions': job.get('subtitle_events', [])}
                image_client = None
                try:
                    if job['options'].get('gemini_image'):
                        from services.gemini_client import GeminiVideoClient
                        from services.call_budget import CallBudget
                        from .orchestrator import RUNTIME_KEY
                        try:
                            image_client = GeminiVideoClient(api_key=RUNTIME_KEY.get())
                            image_client.budget = CallBudget(Path(job['dir']) / 'gemini-budget.sqlite3')
                        except Exception:
                            if image_client is not None:
                                image_client.close()
                                image_client = None
                            pipeline.warn(job, 'AI thumbnails unavailable; using local covers')
                    kit = build(export, job.get('clips') or [], share_plan, job.get('game', 'generic'),
                                client=image_client, job=job)
                finally:
                    if image_client is not None:
                        image_client.close()
                target = Path(job['dir']) / 'share'
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(kit), target)
                import json
                metadata = json.loads((target / 'metadata.json').read_text())
                posting = next(iter(metadata['platforms'].values()))
                link = lambda name: f"/api/jobs/{job.get('id', Path(job['dir']).name)}/share/{name}"
                covers = [dict(url=link(v['file']), label=k) for k, v in metadata['thumbnails'].items()]
                if metadata.get('thumbnail_candidates'):
                    covers = [dict(url=link(v['file']), label=f"Candidate {i+1} · {k} · {c['provider']}")
                              for i, c in enumerate(metadata['thumbnail_candidates'])
                              for k, v in c['variants'].items()]
                job['share_kit'] = dict(metadata=metadata, titles=posting['titles'], description=posting['description'],
                    chapters=(target / 'chapters.txt').read_text(), covers=covers, thumbnails=covers,
                    downloads=[dict(url=link(p.name), label=p.name) for p in sorted(target.iterdir()) if p.is_file()])
    return Path(output)
