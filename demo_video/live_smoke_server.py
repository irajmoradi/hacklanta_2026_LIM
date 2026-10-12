"""Explicit LIVE smoke test: real API, demo-only compatibility and budget adapters.

No production files are modified. Launch only with launch_live.py. A persistent
ledger caps SDK generation attempts across restarts; SDK/provider retries are off.
"""
import hashlib
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
from pipeline import Pipeline
from server.api import create_app
from flask import request, send_from_directory

OUT = Path(os.getenv('DEMO_OUT', '/srv/demo_out/demo01'))
OUT.mkdir(parents=True, exist_ok=True)
BUDGET = Budget(OUT / 'live_calls.json')


class DemoClient(GeminiVideoClient):
    def __init__(self, key):
        super().__init__(api_key=key, vertexai=True, model='gemini-3.5-flash-lite',
                         config=ProviderConfig(attempts=1, chunk_seconds=3600,
                                               timeout_seconds=300, fps=2))
        self.client.models.generate_content = BUDGET.wrap(self.client.models.generate_content)

    def score_windows(self, path, candidates):
        # One real high-resolution window, explicitly bounded for this demo budget.
        return super().score_windows(path, sorted(candidates, key=lambda c: -c['score'])[:1])

    def analyze_video(self, path, prompt=''):
        proxy = OUT / 'full_match_analysis_proxy.mp4'
        if not proxy.exists():
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '4',
                            '-i', str(path), '-vf', 'fps=2,scale=640:-2', '-c:v', 'libx264',
                            '-threads', '4', '-preset', 'fast', '-b:v', '55k', '-maxrate', '55k',
                            '-bufsize', '110k', '-c:a', 'aac', '-ac', '1', '-b:a', '16k',
                            str(proxy)], check=True)
        prompt += ('\nReturn 8 to 12 complete action beats distributed across the match, '
                   'including some mistakes for a roast edit. Prefer 6-10 second clips. '
                   'Do not claim unreadable HUD details. This is a compressed analysis proxy.')
        return super().analyze_video(proxy, prompt)


class DemoPipeline(Pipeline):
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
                    return original(source, **kwargs, sample_fps=2)
                finally:
                    detector.HUDReader = reader
            return signals
        if module == 'privacy' and function == 'sanitize' and original:
            def cached(source, output, payload):
                # Exact source and options cache, shared only by this demo run.
                stat = Path(source).stat()
                digest = hashlib.sha256(json.dumps([str(source), stat.st_size, stat.st_mtime_ns,
                                                   payload], sort_keys=True).encode()).hexdigest()[:16]
                cache = OUT / ('private_' + digest + '.mp4')
                trackfile = cache.with_suffix('.json')
                from privacy import BlurTrack
                if cache.exists() and trackfile.exists():
                    track = BlurTrack.model_validate_json(trackfile.read_text())
                else:
                    _, track = original(source, cache, payload)
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
    data['interest_curve'] = sorted([{'time': (c['start'] + c['end']) / 2,
                                     'score': c['score'] * 100} for c in candidates], key=lambda c: c['time'])
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
