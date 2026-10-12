"""Default pipeline and optional, explicitly enabled import hooks."""
import importlib
import json
import os
import shutil
import subprocess
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from models.effects import effects_for_prompt, sfx_for_prompt
from services.gemini_client import GeminiVideoClient
from services.ffmpeg_runner import FFmpegRunner
from server.legacy import (ATTITUDE_PROMPTS, EDIT_STYLES, _analyze_segment,
                     _offset_clip_timestamps, _split_video, _generate_intro_outro)
from server.validation import clips_valid, plan_valid

ROOT = Path(__file__).resolve().parents[1]


LOG = logging.getLogger(__name__)
REPORT = ContextVar('pipeline_report', default=None)
RUNTIME_KEY = ContextVar('pipeline_runtime_key', default=None)


class Pipeline:
    @contextmanager
    def stage(self, job, name):
        started = time.monotonic()
        job['pipeline_stage'] = name
        report = REPORT.get()
        if report:
            report(job)
        try:
            yield
        finally:
            job['pipeline_stage'] = name
            elapsed = round(time.monotonic() - started, 4)
            job.setdefault('timings', {})[name] = elapsed
            LOG.info('pipeline stage=%s elapsed_seconds=%.4f', name, elapsed)
            if report:
                report(job)

    def run_stage(self, stage, job, key, report):
        token = REPORT.set(report)
        try:
            getattr(self, stage)(job, key)
        finally:
            REPORT.reset(token)

    def warn(self, job, message):
        if message not in job['warnings']:
            job['warnings'].append(message)

    def hook(self, module, function, job):
        try:
            return getattr(importlib.import_module(module), function)
        except (ImportError, AttributeError):
            warning = f'{module}.{function} unavailable; using default behavior'
            if warning not in job['warnings']:
                job['warnings'].append(warning)
            return None

    def client(self, job, key):
        from services.provider_config import validate_provider
        from services.call_budget import CallBudget
        provider = validate_provider(job['options'].get('provider', 'gemini'))
        budget = CallBudget(Path(job['dir']) / 'gemini-budget.sqlite3' if job.get('dir') else None)
        if provider in ('local', 'local_vlm'):
            from .providers import LocalClient
            return LocalClient(api_key=key, budget=budget)
        client = GeminiVideoClient(api_key=key, model=os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite-preview'))
        client.budget = budget
        client.auto_proxy = True
        if os.getenv('GEMINI_ATTEMPTS'):
            client.config = type(client.config).model_validate({**client.config.model_dump(), 'attempts': int(os.environ['GEMINI_ATTEMPTS'])})
        return client

    def analyze(self, job, key):
        options = job['options']
        from services.probe import probe_video
        from .ranking import candidate_dict, rank_merge
        with self.stage(job, 'probe'):
            job['meta'] = probe_video(job['source'])
        from .extensions import analysis_inputs, extra_signals
        source = analysis_inputs(self, job, key)
        job['candidates'] = []
        job['interest_curve'] = []
        with self.stage(job, 'signals'):
            if options.get('use_signals', True):
                detect = self.hook('signals', 'detect_candidates', job)
                if detect:
                    kwargs = dict(profile=job['game'], ocr=True) if options.get('profiles') else {}
                    kwargs['max_candidates'] = max(30, min(500, int(os.getenv('GEMINI_TOP_N', '30')) * 3))
                    import warnings
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter('always', RuntimeWarning)
                        job['candidates'] = [candidate_dict(c) for c in detect(source, curve_sink=lambda curve: job.update(interest_curve=curve), **kwargs)]
                    if caught:
                        self.warn(job, 'Gameplay signal detector degraded; OCR or another optional signal may be unavailable')
        extra_signals(self, job)
        client = self.client(job, key)
        if options.get('profiles'):
            client.profile_prompt = job.get('profile_prompt', '')
        scored = []
        try:
            with self.stage(job, 'window_scoring'):
                if options.get('window_scoring', True) and job['candidates']:
                    score = getattr(client, 'score_windows', None)
                    if callable(score):
                        candidates = job['candidates']
                        from services.gemini_client import GeminiProvider
                        if isinstance(client, GeminiProvider):
                            from services.video_understanding import chunk_ranges
                            splits = options.get('splits', 1)
                            length = job['meta']['duration'] / splits
                            chunks = job.get('_chunks') or [dict(start=i*length, end=(i+1)*length) for i in range(splits)]
                            reserve = sum(len(list(chunk_ranges(c['end']-c['start'], client.config.chunk_seconds,
                                                               client.config.overlap_seconds))) for c in chunks)
                            reserve += 0 if options.get('planner') else 1
                            reserve *= client.config.attempts
                            count = max(0, (client.budget.remaining - reserve) // client.config.attempts)
                            candidates = sorted(candidates, key=lambda c: -c['score'])[:min(count, max(0, int(os.getenv('GEMINI_TOP_N', '30'))))]
                        try:
                            scored = [candidate_dict(c) for c in score(source, candidates)]
                        except Exception as error:
                            from services.provider_errors import classify
                            raise classify(error) from None
                    else:
                        self.warn(job, 'Window scoring unavailable; using signal candidates')
            with self.stage(job, 'whole_video'):
                clips = self.whole_video(job, client)
            with self.stage(job, 'rank_merge'):
                job['window_scores'] = scored
                job['clips'] = clips_valid(rank_merge(job['candidates'], scored, clips), job['meta']['duration'])
        finally:
            close = getattr(client, 'close', None)
            if callable(close):
                close()

    def whole_video(self, job, client):
        options = job['options']
        duration = job['meta']['duration']
        splits = options.get('splits', 1)
        template = (ROOT / 'prompts/clip_finder.txt').read_text(encoding='utf-8')
        prompt = options.get('prompt', '') + '\nFind both highlights and lowlights for later nice or mean planning.'
        prompt += '\n' + job.get('profile_prompt', '')
        if job['candidates']:
            prompt += '\nCandidate windows (verify against video): ' + json.dumps(job['candidates'])
        if job.get('_chunks'):
            segments = [{**c, 'path': Path(c['path'])} for c in job['_chunks']]
        else:
            segments = ([{'path': Path(job.get('_analysis_source', job['source'])), 'start': 0, 'end': duration, 'index': 0}]
                        if splits == 1 else _split_video(Path(job['source']), splits, duration))
        clips = []
        try:
            for seg in segments:
                result = _analyze_segment(seg, template, f"part {seg['index'] + 1} of {len(segments)}", prompt, client)
                if 'error' in result:
                    from services.provider_errors import ProviderFailure
                    raise ProviderFailure(result['error'])
                clips.extend(_offset_clip_timestamps(result['clips'], seg['start']))
        finally:
            if splits > 1 and not job.get('_chunks'):
                for seg in segments:
                    seg['path'].unlink(missing_ok=True)
        excluded = ('spectating', 'kill cam', 'killcam', 'respawn', 'death screen', 'combat report', 'incoming damage', 'camera follows')
        from .ranking import bounded_clips
        clips = bounded_clips(clips, duration)
        clips = [c for c in clips if not any(w in c.get('description', '').lower() for w in excluded)]
        clips.sort(key=lambda c: c['start_seconds'])
        return clips_valid(clips, duration)

    def plan(self, job, key):
        with self.stage(job, 'edit_plan'):
            from .experience import enrich
            job['edit_plan'] = enrich(job, self.plan_edit(job, key))
            job['planning_settings'] = {k: job['options'].get(k) for k in
                ('mode', 'style', 'planner', 'max_duration', 'editing_instructions', 'plan_refinement', 'preset')}

    def plan_edit(self, job, key):
        """Selected/ranked clips in, validated plan out."""
        options = job['options']
        if not any(c.get('keep', True) for c in job['clips'] or []):
            raise ValueError('No selected clips to plan')
        if options.get('planner') or job.get('_local_replan'):
            from .extensions import planner_plan
            try:
                planned = planner_plan(self, job, key)
                if planned:
                    return plan_valid(planned, job['meta']['duration'])
            except (ImportError, ValueError):
                self.warn(job, 'Optional planner unavailable or incompatible; using legacy planner')
        if job.get('_local_replan'):
            raise ValueError('Local planner unavailable; enable the planner module to change mode without paid calls')
        style = EDIT_STYLES[options.get('style', 'hype_montage')]
        prompt = (ROOT / 'prompts/editor.txt').read_text(encoding='utf-8').format(
            max_duration=options.get('max_duration', 180),
            clips_json=json.dumps([c for c in job['clips'] if c.get('keep', True)]),
            video_effects=effects_for_prompt(), sound_effects=sfx_for_prompt(),
            edit_style=style['label'], style_instructions=style['instructions'], user_prompt=options.get('editing_instructions', options.get('prompt', '')))
        client = self.client(job, key)
        try:
            try:
                planned = plan_valid(client.plan_edit(prompt), job['meta']['duration'])
            except Exception as error:
                from services.provider_errors import classify
                raise classify(error) from None
            for segment in planned['segments']:
                clip = next((c for c in job['clips'] if c.get('keep', True) and 'caption' in c
                             and c['start_seconds'] < segment['source_end']
                             and c['end_seconds'] > segment['source_start']), None)
                if clip:
                    segment['title'] = clip['caption']
            return planned
        finally:
            close = getattr(client, 'close', None)
            if callable(close):
                close()

    def render(self, job, key):
        from .rendering import render_job
        token = RUNTIME_KEY.set(key)
        try:
            with self.stage(job, 'render'):
                render_job(self, job, key)
        finally:
            RUNTIME_KEY.reset(token)

    def legacy_render(self, job, key, plan=None):
        # Only this disposable directory contains intermediate render assets.
        scratch = Path(job['dir']) / 'render_tmp'
        scratch.mkdir(exist_ok=True)
        plan = job['edit_plan'] if plan is None else plan
        plan = plan_valid(plan, job['meta']['duration'])
        try:
            preset = (None if job['options'].get('legacy_dimensions') else
                      job['options'].get('preset', 'landscape'))
            width, height = {'landscape': (1920, 1080),
                             'vertical': (1080, 1920), 'square': (1080, 1080),
                             None: (job['meta']['width'], job['meta']['height'])}[preset]
            runner = FFmpegRunner(scratch, Path(job['source']), width, height, job['meta']['fps'],
                                  perf=job['options'].get('perf'))
            output = runner.render(plan)
            if job['options'].get('generate_thumbnails', False):
                client = self.client(job, key)
                try:
                    intro, outro = _generate_intro_outro(runner, job['meta']['duration'], client)
                finally:
                    close = getattr(client, 'close', None)
                    if callable(close):
                        close()
                parts = [p for p in (intro, output, outro) if p]
                if len(parts) > 1:
                    manifest = scratch / 'thumb_concat.txt'
                    manifest.write_text(''.join(f"file '{p.resolve().as_posix()}'\n" for p in parts))
                    output = scratch / 'with_thumbnails.mp4'
                    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(manifest),
                                    '-c', 'copy', str(output)], check=True, capture_output=True, timeout=3600)
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError('Renderer produced no output')
            destination = Path(job['dir']) / 'output.mp4'
            os.replace(output, destination)
            job['output'] = str(destination)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
