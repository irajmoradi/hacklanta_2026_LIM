"""Explicit LIVE smoke test: real API, demo-only compatibility and budget adapters.

No production files are modified. Launch only with launch_live.py. A persistent
ledger caps SDK generation attempts across restarts; SDK/provider retries are off.
"""
import hashlib
import copy
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'full_app'))
from budget import Budget
from services.gemini_client import GeminiVideoClient
from services.video_understanding import ProviderConfig
from models.schemas import ClipList, WindowAssessment, ScoredWindow
from pydantic import BaseModel
from google.genai import types
from pipeline import Pipeline
from server.api import create_app
from flask import request, send_from_directory

OUT = Path(os.getenv('DEMO_OUT', '/srv/demo_out/demo01'))
OUT.mkdir(parents=True, exist_ok=True)
BUDGET = Budget(OUT / 'live_calls.json')
PRIVACY_REGIONS = {
    'kill_feed': {'x': .64, 'y': .03, 'width': .36, 'height': .27},
    'chat': {'x': 0., 'y': .55, 'width': .4, 'height': .4},
    'party_voice': {'x': 0., 'y': 0., 'width': .25, 'height': .35},
}


class CombinedAssessment(BaseModel):
    moments: ClipList
    window: WindowAssessment


def compatible_schema(value):
    """SDK Schema lacks exclusiveMinimum; local Pydantic validation stays strict."""
    if isinstance(value, list):
        return [compatible_schema(v) for v in value]
    if isinstance(value, dict):
        return {('minimum' if k == 'exclusiveMinimum' else k): compatible_schema(v)
                for k, v in value.items()}
    return value


def remap_selected(plan, clips):
    """Map the selected source ranges onto a concatenated, source-speed reel."""
    result = copy.deepcopy(plan)
    mapped, ranges, cursor = [], [], 0.
    for index, segment in enumerate(result['segments']):
        start, end = segment['source_start'], segment['source_end']
        ranges.append((start, end))
        segment.update(source_start=cursor, source_end=cursor + end - start)
        for clip in clips or []:
            left, right = max(start, clip['start_seconds']), min(end, clip['end_seconds'])
            if left < right:
                mapped.append({**clip, 'id': f"{clip['id']}_{index}",
                               'start_seconds': cursor + left - start,
                               'end_seconds': cursor + right - start})
        cursor += end - start
    return result, mapped, ranges


class DemoClient(GeminiVideoClient):
    def __init__(self, key):
        super().__init__(api_key=key, vertexai=True, model='gemini-3.5-flash-lite',
                         config=ProviderConfig(attempts=1, chunk_seconds=3600,
                                               timeout_seconds=300, fps=2))
        self.client.models.generate_content = BUDGET.wrap(self.client.models.generate_content)
        self.combined = None

    def _generation_config(self, schema, temperature, video):
        return types.GenerateContentConfig(response_mime_type='application/json',
            response_json_schema=compatible_schema(schema.model_json_schema()), temperature=temperature,
            **({'media_resolution': self.media_resolution} if video else {}))

    def score_windows(self, path, candidates):
        candidate = sorted(candidates, key=lambda c: -c['score'])[0]
        cached = OUT / 'combined_result.json'
        if cached.exists():
            saved = json.loads(cached.read_text())
            if saved['candidate'] != candidate:
                raise ValueError('Cached assessment belongs to a different window; refusing to reuse')
            self.combined = CombinedAssessment.model_validate(saved['response'])
        else:
            proxy = self.proxy(path)
            prompt = ('Analyze this complete Valorant match. Return 8 to 12 complete action beats '
                      'spread across the match, including some mistakes. Prefer 6-10 second clips. '
                      'Use numeric original-source seconds; start and start_seconds must match exactly, '
                      'as must end and end_seconds. Do not claim unreadable HUD details. '
                      'In the window field, assess ONLY this candidate window: ' + json.dumps(candidate) +
                      '\nSet player_alive false for spectating/death screens, null if uncertain. '
                      'hype is 0-10. Caption describes visible evidence. ' + getattr(self, 'profile_prompt', ''))
            self.combined = self._infer(proxy, prompt, CombinedAssessment)
            cached.write_text(json.dumps({'candidate': candidate, 'response': self.combined.model_dump()}, indent=2))
        assessment = self.combined.window.model_dump()
        if assessment['player_alive'] is not True:
            assessment.update(kind='neutral', hype=0.)
        return [ScoredWindow(**candidate, **assessment)]

    def proxy(self, path):
        proxy = OUT / 'full_match_analysis_proxy.mp4'
        if not proxy.exists():
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '4',
                            '-i', str(path), '-vf', 'fps=2,scale=640:-2', '-c:v', 'libx264',
                            '-threads', '4', '-preset', 'fast', '-b:v', '55k', '-maxrate', '55k',
                            '-bufsize', '110k', '-c:a', 'aac', '-ac', '1', '-b:a', '16k',
                            str(proxy)], check=True)
        return proxy

    def analyze_video(self, path, prompt=''):
        if self.combined is not None:
            from services.video_understanding import video_duration
            duration = video_duration(path)
            valid = [c for c in self.combined.moments.clips if c.end <= duration and c.start < duration]
            rejected = [c.model_dump() for c in self.combined.moments.clips if c.end > duration or c.start >= duration]
            (OUT / 'rejected_ranges.json').write_text(json.dumps(rejected, indent=2))
            return ClipList(clips=valid)
        proxy = self.proxy(path)
        prompt += ('\nReturn 8 to 12 complete action beats distributed across the match, '
                   'including some mistakes for a roast edit. Prefer 6-10 second clips. '
                   'Do not claim unreadable HUD details. This is a compressed analysis proxy.')
        return super().analyze_video(proxy, prompt)


class DemoPipeline(Pipeline):
    def render(self, job, key):
        if os.getenv('DEMO_REPLAY_EXPORTS') == 'true':
            preset = job['options'].get('preset', 'landscape')
            saved = json.loads((OUT / (preset + '.json')).read_text())
            with Path(job['source']).open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            fingerprint = json.loads((OUT / 'local_candidates_source.json').read_text())['sha256']
            if digest != fingerprint or job['edit_plan'] != saved['edit_plan'] or job['options'] != saved['options']:
                raise ValueError('UI replay request does not match the verified source, plan and export options')
            with self.stage(job, 'verified_export_cache'):
                destination = Path(job['dir']) / 'output.mp4'
                shutil.copy2(OUT / ('montage_' + preset + '.mp4'), destination)
                shutil.copytree(OUT / ('share_' + preset), Path(job['dir']) / 'share', dirs_exist_ok=True)
                job.update(output=str(destination), share_kit='share', demo_cached_render=True)
            return
        original_clips = job.get('clips')
        try:
            return super().render(job, key)
        finally:
            job['clips'] = original_clips

    def run_stage(self, stage, job, key, report):
        try:
            return super().run_stage(stage, job, key, report)
        except Exception as error:
            message = str(error)
            for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY'):
                if os.getenv(name):
                    message = message.replace(os.environ[name], '[REDACTED]')
            (OUT / 'pipeline_error.txt').write_text(f'{stage}: {type(error).__name__}: {message}')
            raise

    def client(self, job, key):
        return DemoClient(key or os.environ['GOOGLE_API_KEY'])

    def hook(self, module, function, job):
        original = super().hook(module, function, job)
        if module == 'profiles' and function == 'detect_game' and original:
            def detect(source):
                detected = original(source)
                (OUT / 'profile_detection.json').write_text(json.dumps({'automatic': detected}))
                if detected[0] == 'generic':
                    self.warn(job, 'Auto detection inconclusive; DEMO-01 uses the supplied Valorant footage label')
                    return 'valorant', 0.
                return detected
            return detect
        if module == 'signals' and function == 'detect_candidates' and original:
            def signals(source, **kwargs):
                import signals.detector as detector
                manifest = OUT / 'local_candidates_source.json'
                cache = OUT / 'local_candidates.json'
                with Path(source).open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if manifest.exists() and cache.exists() and json.loads(manifest.read_text())['sha256'] == digest:
                    from signals import Candidate
                    self.warn(job, 'DEMO-01 reuses real cached local signals after provider validation failure')
                    return [Candidate(**c) for c in json.loads(cache.read_text())]
                reader = detector.HUDReader
                class BoundedOCR(reader):
                    def __init__(self, *args, **options):
                        super().__init__(*args, **options)
                        self.next_sample = 0.
                    def read(self, frame, timestamp):
                        if timestamp < self.next_sample:
                            return []
                        self.next_sample = timestamp + 5.
                        return super().read(frame, timestamp)
                detector.HUDReader = BoundedOCR
                try:
                    result = original(source, **kwargs, sample_fps=2)
                    from dataclasses import asdict
                    (OUT / 'local_candidates.json').write_text(json.dumps([asdict(c) for c in result], indent=2))
                    manifest.write_text(json.dumps({'sha256': digest}))
                    return result
                finally:
                    detector.HUDReader = reader
            return signals
        if module == 'privacy' and function == 'sanitize' and original:
            def cached(source, output, payload):
                # Extract reviewed ranges at source speed, then sanitize before
                # effects/framing. Preserve source-relative API state on return.
                remapped, clips, ranges = remap_selected(job['edit_plan'], job.get('clips'))
                stat = Path(source).stat()
                digest = hashlib.sha256(json.dumps([str(source), stat.st_size, stat.st_mtime_ns,
                                                   payload, ranges], sort_keys=True).encode()).hexdigest()[:16]
                selected = OUT / ('selected_' + digest + '.mp4')
                if not selected.exists():
                    inputs, graph, joins = [], [], []
                    for i, (start, end) in enumerate(ranges):
                        inputs += ['-ss', str(start), '-t', str(end-start), '-i', str(source)]
                        graph += [f'[{i}:v]fps=30,setpts=PTS-STARTPTS[v{i}]',
                                  f'[{i}:a]asetpts=PTS-STARTPTS[a{i}]']
                        joins.append(f'[v{i}][a{i}]')
                    graph.append(''.join(joins) + f'concat=n={len(ranges)}:v=1:a=1[v][a]')
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *inputs,
                                    '-filter_complex_threads', '1', '-filter_complex', ';'.join(graph),
                                    '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-threads', '4',
                                    '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                                    '-c:a', 'aac', str(selected)], check=True)
                job['edit_plan'], job['clips'] = remapped, clips
                (OUT / ('selection_' + digest + '.json')).write_text(json.dumps({'ranges': ranges, 'remapped': remapped}, indent=2))
                cache = OUT / ('private_' + digest + '.mp4')
                trackfile = cache.with_suffix('.json')
                from privacy import BlurTrack
                if cache.exists() and trackfile.exists():
                    track = BlurTrack.model_validate_json(trackfile.read_text())
                else:
                    cache.unlink(missing_ok=True)  # This exact generated cache may be incomplete after interruption.
                    _, track = original(selected, cache, payload)
                    trackfile.write_text(track.model_dump_json())
                os.link(cache, output)
                return Path(output), track
            return cached
        return original


def translate_options(data):
    for ui, api in [('planner_v2', 'planner'), ('privacy_blur', 'privacy'), ('share_kit', 'social')]:
        if ui in data:
            data[api] = data.pop(ui)
    if 'game' in data:
        data['profiles'] = True
    return data


def wire_job(data, workspace):
    if not isinstance(data, dict) or not data.get('job_id'):
        return data
    candidates = data.get('candidates', [])
    scale = max([1., *[c['score'] for c in candidates]])
    data['interest_curve'] = sorted([{'time': (c['start'] + c['end']) / 2,
                                     'score': max(0., c['score']) / scale * 100} for c in candidates], key=lambda c: c['time'])
    data['source_url'] = f"/api/stream/{data['job_id']}"
    if data.get('share_kit') == 'share':
        folder = Path(workspace) / data['job_id'] / 'share'
        meta = json.loads((folder / 'metadata.json').read_text())
        posting = next(iter(meta['platforms'].values()))
        link = lambda name: f"/api/jobs/{data['job_id']}/share/{name}"
        data['share_kit'] = dict(titles=posting['titles'], description=posting['description'],
                                chapters=(folder / 'chapters.txt').read_text(),
                                thumbnails=[dict(url=link(v['file']), label=k) for k, v in meta['thumbnails'].items()],
                                downloads=[dict(url=link(p.name), label=p.name) for p in sorted(folder.iterdir()) if p.is_file()])
    return data


def make_app(workspace=None, pipeline=None):
    workspace = str(workspace or OUT / 'jobs')
    app = create_app({'WORKSPACE': workspace, 'JOB_WORKERS': 1, 'RECOVER_JOBS': False}, pipeline or DemoPipeline())
    app.static_folder = str(ROOT / 'full_app/production_frontend/dist')

    @app.get('/assets/<path:name>')
    def assets(name):
        return send_from_directory(Path(app.static_folder) / 'assets', name)

    @app.before_request
    def translate():
        if request.is_json and request.path.endswith(('/analyze', '/render', '/plan')):
            data = request.get_json()
            if isinstance(data, dict):
                translate_options(data)
                if request.path.endswith('/analyze'):
                    data.setdefault('max_duration', 45)
                    data.setdefault('privacy_options', {'backend': 'none'})
                if data.get('privacy_options', {}).get('backend') == 'none':
                    # Whole-region fallback must not blanket the central action.
                    # This explicit demo profile covers named HUD areas only.
                    data['privacy_options'].setdefault('regions', PRIVACY_REGIONS)

    @app.after_request
    def adapt(response):
        if response.is_json and response.status_code < 400:
            data = response.get_json()
            if request.path == '/api/info':
                data['frontend_capabilities'] = dict(options=['game', 'window_scoring', 'planner_v2',
                                                              'privacy_blur', 'share_kit', 'sam_reframe'])
            response.set_data(app.json.dumps(wire_job(data, workspace)))
        return response
    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    # HTTP request debug logs can include credentials; keep provider transport quiet.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    pack = ROOT / 'full_app/reaction_packs/team'
    shutil.copytree('/srv/packs/team', pack, dirs_exist_ok=True)
    os.environ['REACTION_PACK'] = str(pack)
    os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'true'
    os.environ['GEMINI_MODEL'] = 'gemini-3.5-flash-lite'
    make_app().run(host='127.0.0.1', port=8011, threaded=True, use_reloader=False)
