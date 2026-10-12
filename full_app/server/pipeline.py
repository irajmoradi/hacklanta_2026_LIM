"""Default pipeline and optional, explicitly enabled import hooks."""
import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from models.effects import effects_for_prompt, sfx_for_prompt
from services.gemini_client import GeminiVideoClient
from services.ffmpeg_runner import FFmpegRunner
from .legacy import (ATTITUDE_PROMPTS, EDIT_STYLES, _analyze_segment,
                     _offset_clip_timestamps, _split_video, _generate_intro_outro)
from .validation import clips_valid, plan_valid

ROOT = Path(__file__).resolve().parents[1]


class Pipeline:
    def hook(self, module, function, job):
        try:
            return getattr(importlib.import_module(module), function)
        except (ImportError, AttributeError):
            warning = f'{module}.{function} unavailable; using default behavior'
            if warning not in job['warnings']:
                job['warnings'].append(warning)
            return None

    def client(self, job, key):
        provider = job['options'].get('provider', 'gemini')
        if provider != 'gemini':
            factory = self.hook('services.providers', 'get_provider', job)
            if factory:
                return factory(provider, api_key=key)
        key = key or os.getenv('GEMINI_API_KEY')
        if not key:
            raise ValueError('Set GEMINI_API_KEY or supply X-API-Key')
        return GeminiVideoClient(api_key=key, model=os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite-preview'))

    def analyze(self, job, key):
        options = job['options']
        if options.get('use_signals'):
            detect = self.hook('signals', 'detect_candidates', job)
            if detect:
                job['candidates'] = detect(job['source'])
        client = self.client(job, key)
        duration = job['meta']['duration']
        splits = options.get('splits', 1)
        template = (ROOT / 'prompts/clip_finder.txt').read_text(encoding='utf-8')
        prompt = options.get('prompt', '') + ATTITUDE_PROMPTS[options.get('mode', 'nice')]
        if job['candidates']:
            prompt += '\nCandidate windows (verify against video): ' + json.dumps(job['candidates'])
        segments = ([{'path': Path(job['source']), 'start': 0, 'end': duration, 'index': 0}]
                    if splits == 1 else _split_video(Path(job['source']), splits, duration))
        clips = []
        try:
            for seg in segments:
                result = _analyze_segment(seg, template, f"part {seg['index'] + 1} of {splits}", prompt, client)
                if 'error' in result:
                    raise RuntimeError('Video analysis failed')
                clips.extend(_offset_clip_timestamps(result['clips'], seg['start']))
        finally:
            if splits > 1:
                for seg in segments:
                    seg['path'].unlink(missing_ok=True)
        excluded = ('spectating', 'kill cam', 'killcam', 'respawn', 'death screen', 'combat report', 'incoming damage', 'camera follows')
        clips = [c for c in clips if not any(w in c.get('description', '').lower() for w in excluded)]
        clips.sort(key=lambda c: c['start_seconds'])
        job['clips'] = clips_valid(clips, duration)

    def plan(self, job, key):
        options = job['options']
        style = EDIT_STYLES[options.get('style', 'hype_montage')]
        prompt = (ROOT / 'prompts/editor.txt').read_text(encoding='utf-8').format(
            max_duration=options.get('max_duration', 180),
            clips_json=json.dumps([c for c in job['clips'] if c.get('keep', True)]),
            video_effects=effects_for_prompt(), sound_effects=sfx_for_prompt(),
            edit_style=style['label'], style_instructions=style['instructions'], user_prompt=options.get('prompt', ''))
        job['edit_plan'] = plan_valid(self.client(job, key).plan_edit(prompt), job['meta']['duration'])

    def render(self, job, key):
        # Only this disposable directory contains intermediate render assets.
        scratch = Path(job['dir']) / 'render_tmp'
        scratch.mkdir(exist_ok=True)
        plan = job['edit_plan']
        for feature in ('captions', 'reactions', 'sam'):
            if job['options'].get(feature):
                hook = self.hook(feature, 'apply', job)
                if hook:
                    plan = hook(job=job, plan=plan, workspace=scratch)
        plan = plan_valid(plan, job['meta']['duration'])
        render_hook = self.hook('render', 'render_job', job) if os.getenv('ENABLE_RENDER_HOOK') == '1' else None
        try:
            if render_hook:
                output = Path(render_hook(job=job, plan=plan, workspace=scratch))
            else:
                preset = job['options'].get('preset', 'landscape')
                width, height = {'landscape': (job['meta']['width'], job['meta']['height']),
                                 'vertical': (1080, 1920), 'square': (1080, 1080)}[preset]
                runner = FFmpegRunner(scratch, Path(job['source']), width, height, job['meta']['fps'])
                output = runner.render(plan)
                if job['options'].get('generate_thumbnails', False):
                    intro, outro = _generate_intro_outro(runner, job['meta']['duration'], self.client(job, key))
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
