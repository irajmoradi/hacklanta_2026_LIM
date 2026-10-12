"""Application factory and compatible HTTP adapters."""
import atexit
import os
import shutil
import time
import uuid
import threading
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from models.effects import VIDEO_EFFECTS, SOUND_EFFECTS
from .resources import Resources, IsolatedPipeline, probe
from .auth import install_auth
from .security import validate_media_metadata
from .legacy import EDIT_STYLES
from .pipeline import Pipeline, ROOT
from .ownership import WorkspaceLease
from .queue import Conflict, JobQueue
from .store import JobStore
from .validation import clips_valid, options_valid, plan_valid


def public(job):
    data = {k: v for k, v in job.items() if k not in ('dir', 'source', 'output', 'sources') and not k.startswith('_')}
    data.update(job_id=job['id'], plan=job['edit_plan'],
                has_clips=job['clips'] is not None, has_plan=job['edit_plan'] is not None,
                has_output=job['output'] is not None,
                download_url=f"/api/jobs/{job['id']}/download" if job['output'] else None)
    return data


def body():
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError('JSON body must be an object')
    return data


def create_app(config=None, pipeline=None):
    app = Flask(__name__, static_folder=str(ROOT / 'frontend'), static_url_path='')
    app.config.update(WORKSPACE=os.getenv('JOB_WORKSPACE', str(ROOT / 'workspace')),
                      MAX_CONTENT_LENGTH=int(os.getenv('MAX_UPLOAD_BYTES', 2 * 1024**3)),
                      JOB_WORKERS=int(os.getenv('JOB_WORKERS', 2)), JOB_CAPACITY=32,
                      SSE_INTERVAL=1, SSE_MAX_SECONDS=30, SSE_MAX_SUBSCRIBERS=8, RECOVER_JOBS=True,
                      MAX_JOBS=200, MAX_UPLOADS=2, MAX_JSON_BYTES=2 * 1024**2, WORKSPACE_BYTES=20 * 1024**3,
                      OWNER_BYTES=10 * 1024**3, JOB_BYTES=4 * 1024**3,
                      DISK_HEADROOM_BYTES=512 * 1024**2, JOB_TTL_SECONDS=7 * 86400,
                      RETENTION_INTERVAL=60, STAGE_TIMEOUT_SECONDS=1800,
                      STAGE_MEMORY_BYTES=8 * 1024**3, PROBE_TIMEOUT_SECONDS=20,
                      PROBE_MEMORY_BYTES=1024**3, MAX_MEDIA_DURATION=43200,
                      MAX_MEDIA_PIXELS=3840 * 2160, MAX_MEDIA_FPS=120,
                      MAX_MEDIA_PIXEL_RATE=3840 * 2160 * 60, MAX_MEDIA_FRAMES=3000000)
    # Numeric limits can be configured without custom application code.
    for name in tuple(app.config):
        if name.startswith(('SSE_', 'MAX_', 'WORKSPACE_BYTES', 'OWNER_BYTES', 'JOB_BYTES',
                            'DISK_HEADROOM', 'JOB_TTL', 'RETENTION_', 'STAGE_', 'PROBE_')) and 'LIM_' + name in os.environ:
            app.config[name] = int(os.environ['LIM_' + name])
    app.config.update(config or {})
    workspace = Path(app.config['WORKSPACE']).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    lease = WorkspaceLease(workspace / '.worker.lock')
    store = JobStore(workspace / 'jobs.sqlite3')
    try:
        owned = install_auth(app, store)
    except Exception:
        lease.close()
        raise
    resources = Resources(workspace, store, app.config)
    default_pipeline = (Pipeline() if app.testing and not app.config.get('ISOLATE_STAGES')
                        else IsolatedPipeline(resources))
    queue = JobQueue(store, pipeline if pipeline is not None else default_pipeline,
                     app.config['JOB_WORKERS'], app.config['JOB_CAPACITY'], lease)
    streams = threading.BoundedSemaphore(app.config['SSE_MAX_SUBSCRIBERS'])
    uploads = threading.BoundedSemaphore(app.config['MAX_UPLOADS'])
    queue.start_retention(resources, app.config['RETENTION_INTERVAL'])
    app.extensions.update(job_store=store, job_queue=queue)
    atexit.register(queue.close)
    # Only UUID job directories under this workspace are owned by this backend.
    known = {job['id'] for job in store.all()}
    for directory in workspace.iterdir():
        if not directory.is_dir() or directory.is_symlink() or len(directory.name) != 32:
            continue
        try:
            int(directory.name, 16)
        except ValueError:
            continue
        if directory.name not in known:
            shutil.rmtree(directory)
        else:
            for name in ('render_tmp', 'extensions_tmp'):
                scratch = directory / name
                if scratch.is_dir() and not scratch.is_symlink():
                    shutil.rmtree(scratch)
            (directory / 'upload.part').unlink(missing_ok=True)
            for segment in directory.glob('seg_*_source.mp4'):
                segment.unlink(missing_ok=True)
    if app.config['RECOVER_JOBS']:
        queue.recover()

    @app.errorhandler(KeyError)
    def missing(exc):
        return jsonify(error='Job not found'), 404

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 409 if isinstance(exc, Conflict) else 400

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.description), exc.code

    @app.get('/')
    def index():
        response = send_from_directory(app.static_folder, 'index.html')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    @app.get('/api/health')
    def health():
        return jsonify(status='ok')

    @app.get('/api/info')
    def info():
        return jsonify(model=os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite-preview'),
                       has_api_key=bool(os.getenv('GEMINI_API_KEY')),
                       video_effects={k: v['description'] for k, v in VIDEO_EFFECTS.items()},
                       sound_effects={k: v['description'] for k, v in SOUND_EFFECTS.items() if v['file']},
                       edit_styles={k: v['label'] for k, v in EDIT_STYLES.items()})

    @app.post('/api/upload')
    @app.post('/api/jobs')
    def upload():
        if request.content_length is None and not request.mimetype:
            raise ValueError('No video file provided (multipart field: video)')
        if request.content_length is None:
            return jsonify(error='Content-Length required for upload reservation'), 411
        if request.content_length > app.config['MAX_CONTENT_LENGTH']:
            return jsonify(error='Upload too large'), 413
        if not uploads.acquire(blocking=False):
            return jsonify(error='Upload capacity exhausted'), 429
        try:
            resources.reap(queue)
            with resources.upload(g.owner, request.content_length):
                return receive_upload()
        finally:
            uploads.release()

    def metadata(path):
        meta = validate_media_metadata(probe(path, app.config),
            max_duration=app.config['MAX_MEDIA_DURATION'], max_pixels=app.config['MAX_MEDIA_PIXELS'],
            max_fps=app.config['MAX_MEDIA_FPS'], max_pixel_rate=app.config['MAX_MEDIA_PIXEL_RATE'])
        if meta['duration'] * meta['fps'] > app.config['MAX_MEDIA_FRAMES']:
            raise ValueError('Video exceeds frame count limit')
        return meta

    def receive_upload():
        video = request.files.get('video')
        if not video or not video.filename:
            raise ValueError('No video file provided (multipart field: video)')
        job_id = uuid.uuid4().hex
        directory = workspace / job_id
        directory.mkdir()
        temporary = directory / 'upload.part'
        try:
            video.save(temporary)
            meta = metadata(temporary)
            source = directory / 'source.mp4'
            temporary.replace(source)
            videos = request.files.getlist('video')
            if len(videos) > 8:
                raise ValueError('At most eight team recordings are supported')
            sources = [str(source)]
            for index, extra in enumerate(videos[1:], 1):
                path = directory / f'source_{index}.mp4'
                extra.save(path)
                metadata(path)
                sources.append(str(path))
            job = dict(id=job_id, _owner=g.owner, dir=str(directory), source=str(source), meta=meta,
                       sources=sources, source_count=len(sources),
                       status='uploaded', stage='upload', progress=1, completed=['upload'],
                       options={}, clips=None, candidates=[], edit_plan=None, output=None,
                       warnings=[], error=None, created_at=time.time(), target=None, elapsed=0)
            store.save(job)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise ValueError('Upload is not a readable video') from None
        return jsonify(public(job)), 200 if request.path == '/api/upload' else 201

    @app.get('/api/jobs/<job_id>')
    @app.get('/api/status/<job_id>')
    def status(job_id):
        return jsonify(public(store.get(job_id)))

    def start(job_id, target, data, legacy=False, analysis_request=False):
        options = options_valid(data, EDIT_STYLES)
        job = owned(job_id)
        if 'edit_plan' in data and target != 'render':
            raise ValueError('edit_plan is only accepted by render')
        custom = plan_valid(data['edit_plan'], job['meta']['duration'],
                            options.get('max_duration', job['options'].get('max_duration', 180))) if 'edit_plan' in data else None
        key = request.headers.get('X-API-Key') or data.get('api_key')
        if key is not None and (not isinstance(key, str) or len(key) > 4096):
            raise ValueError('Invalid API key')
        if legacy and target == 'render':
            options.setdefault('generate_thumbnails', True)
        if target == 'render':
            options['legacy_dimensions'] = legacy and 'preset' not in options
        future = queue.submit(job_id, target, options, key, custom, analysis_request=analysis_request)
        if legacy:
            future.result()
            job = store.get(job_id)
            if job['status'] == 'error':
                return jsonify(error=job['error']), 500
            if job['status'] == 'cancelled':
                return jsonify(error='Job cancelled'), 409
            result = public(job)
            result['splits'] = job['options'].get('splits', 1)
            return jsonify(result)
        return jsonify(public(store.get(job_id))), 202

    @app.post('/api/jobs/<job_id>/analyze')
    def analyze(job_id):
        # The new workflow includes planning; legacy clients have a separate button.
        return start(job_id, 'plan', body(), analysis_request=True)

    @app.post('/api/jobs/<job_id>/plan')
    def plan(job_id):
        return start(job_id, 'plan', body())

    @app.post('/api/jobs/<job_id>/render')
    def render(job_id):
        data = body()
        data.setdefault('preset', 'landscape')
        return start(job_id, 'render', data)

    @app.post('/api/analyze')
    @app.post('/api/plan')
    @app.post('/api/render')
    def legacy_stage():
        data = body()
        job_id = data.get('job_id')
        if not isinstance(job_id, str):
            raise ValueError('job_id is required')
        return start(job_id, request.path.rsplit('/', 1)[1], data, legacy=True)

    @app.post('/api/jobs/<job_id>/cancel')
    def cancel(job_id):
        return jsonify(public(queue.cancel(job_id)))

    @app.patch('/api/jobs/<job_id>/clips')
    def edit_clips(job_id):
        data = body()
        if set(data) != {'clips'}:
            raise ValueError('Provide clips in the desired order')
        with queue.lock:
            job = store.get(job_id)
            if job_id in queue.active:
                raise Conflict('Job is busy')
            if job['clips'] is None:
                raise Conflict('Analyze before editing clips')
            if isinstance(data['clips'], list) and any(not isinstance(c, dict) or 'id' not in c for c in data['clips']):
                raise ValueError('Each edited clip must include its id')
            incoming = clips_valid(data['clips'], job['meta']['duration'])
            known = {c['id']: c for c in job['clips']}
            edited = []
            for clip in incoming:
                if clip['id'] not in known:
                    raise ValueError('Unknown clip id')
                merged = dict(known[clip['id']], **clip)
                # Keep textual timestamp aliases synchronized for older providers.
                merged.update(start=str(clip['start_seconds']), end=str(clip['end_seconds']))
                edited.append(merged)
            job['clips'] = edited
            queue.invalidate(job, 'plan')
            job.update(status='analyzed', stage='analyze', error=None)
            store.save(job)
            return jsonify(public(job))

    def media_path(job, path):
        directory = Path(job['dir']).resolve()
        target = Path(path).resolve()
        if directory != workspace / job['id'] or not target.is_relative_to(directory):
            raise KeyError(job['id'])
        return target

    @app.get('/api/jobs/<job_id>/download')
    @app.get('/api/download/<job_id>')
    def download(job_id):
        job = store.get(job_id)
        if job['status'] != 'done' or not job['output'] or not Path(job['output']).is_file():
            return jsonify(error='No rendered output yet'), 404
        return send_file(media_path(job, job['output']), mimetype='video/mp4', as_attachment=True,
                         download_name=f'highlight_{job_id}.mp4')

    @app.get('/api/stream/<job_id>')
    def stream(job_id):
        job = store.get(job_id)
        return send_file(media_path(job, job['source']), mimetype='video/mp4', conditional=True)

    @app.get('/api/jobs/<job_id>/share/<path:filename>')
    def share(job_id, filename):
        job = store.get(job_id)
        if job['status'] != 'done' or not job.get('share_kit'):
            return jsonify(error='No share kit yet'), 404
        target = media_path(job, Path(job['dir']) / 'share' / filename)
        if not target.is_relative_to((Path(job['dir']) / 'share').resolve()) or not target.is_file():
            raise KeyError(job_id)
        return send_file(target, as_attachment=True)

    @app.get('/api/log/<job_id>')
    def log(job_id):
        store.get(job_id)
        return Response('\n'.join(row[1] for row in store.events(job_id, 0)) + '\n', mimetype='text/plain')

    @app.get('/api/jobs/<job_id>/events')
    def events(job_id):
        store.get(job_id)
        try:
            after = int(request.headers.get('Last-Event-ID', request.args.get('after', 0)))
            if after < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Last-Event-ID / after must be a nonnegative integer') from None

        if not streams.acquire(blocking=False):
            return jsonify(error='Event subscriber capacity exhausted'), 429, {'Retry-After': '1'}
        released = False
        def release():
            nonlocal released
            if not released:
                released = True
                streams.release()

        def generate():
            cursor = after
            deadline = time.monotonic() + app.config['SSE_MAX_SECONDS']
            try:
                yield from replay(cursor, deadline)
            finally:
                release()

        def replay(cursor, deadline):
            while time.monotonic() < deadline:
                rows = store.events(job_id, cursor)
                for seq, data in rows:
                    cursor = seq
                    yield f'id: {seq}\nevent: progress\ndata: {data}\n\n'
                if not rows:
                    try:
                        store.get(job_id)
                    except KeyError:
                        return
                    yield ': heartbeat\n\n'
                try:
                    current = store.get(job_id)
                except KeyError:
                    return
                # Drain all replay pages, then close inactive/terminal jobs.
                if len(rows) < 100 and current['status'] not in ('queued', 'analyzing', 'planning', 'rendering'):
                    return
                time.sleep(min(app.config['SSE_INTERVAL'], max(0, deadline - time.monotonic())))
        response = Response(generate(), mimetype='text/event-stream',
                            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
        response.call_on_close(release)
        return response

    @app.delete('/api/jobs/<job_id>')
    def delete(job_id):
        with queue.lock:
            job = store.get(job_id)
            if job_id in queue.active:
                raise Conflict('Cancel and wait for the worker before deleting')
            directory = Path(job['dir']).resolve()
            if directory.parent != workspace:
                raise Conflict('Invalid job directory')
            shutil.rmtree(directory, ignore_errors=True)
            with store.connection() as db:
                db.execute('DELETE FROM events WHERE job_id=?', (job_id,))
                db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            queue.keys.pop(job_id, None)
        return '', 204

    return app
