"""Bounded, single-process worker pool with durable stage checkpoints."""
import time
import threading
import shutil
from .validation import plan_valid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class Conflict(ValueError):
    pass


class JobQueue:
    STAGES = ('analyze', 'plan', 'render')

    def __init__(self, store, pipeline, workers=2, capacity=32, lease=None):
        self.store, self.pipeline = store, pipeline
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='job')
        self.capacity = capacity
        self.active = {}
        self.keys = {}  # Never serialized, logged, or returned in status.
        self.lock = store.lock
        self.lease = lease
        self.stop_retention = threading.Event()
        self.retention_thread = None

    def start_retention(self, resources, interval):
        def maintain():
            while not self.stop_retention.wait(interval):
                resources.reap(self)
        self.retention_thread = threading.Thread(target=maintain, daemon=True, name='job-retention')
        self.retention_thread.start()

    def recover(self):
        for job in self.store.all():
            # A cancelled job is never resurrected on restart.
            if job['status'] in ('queued', 'analyzing', 'planning', 'rendering'):
                try:
                    self.submit(job['id'], job['target'], {}, recover=True)
                except ValueError:
                    job.update(status='error', error='Stored job no longer passes admission; submit a valid plan')
                    self.store.save(job)

    def submit(self, job_id, target, options, key=None, custom_plan=None, recover=False, analysis_request=False):
        with self.lock:
            job = self.store.get(job_id)
            if job_id in self.active:
                same_options = all(job['options'].get(k) == v for k, v in options.items())
                same_plan = custom_plan is None or custom_plan == job['edit_plan']
                if job['target'] == target and same_options and same_plan and job['status'] != 'cancelled':
                    return self.active[job_id]
                raise Conflict('Job is busy')
            if len(self.active) >= self.capacity and not recover:
                raise Conflict('Queue is full; retry later')
            candidate = custom_plan if custom_plan is not None else job['edit_plan'] if target == 'render' else None
            if candidate is not None:
                plan_valid(candidate, job['meta']['duration'],
                           options.get('max_duration', job['options'].get('max_duration', 180)))
            if key:
                self.keys[job_id] = key
            changed = {k for k, v in options.items() if job['options'].get(k) != v}
            analysis_keys = {'provider', 'use_signals', 'window_scoring', 'splits',
                             'profiles', 'game', 'audio_ai', 'vjepa', 'ingest', 'chat', 'multipov'}
            # Prompt belongs to the stage requested by the caller.
            if analysis_request or target == 'analyze' or (target == 'plan' and not job['clips']):
                analysis_keys |= {'prompt'}
            invalidate = None
            if changed & analysis_keys:
                invalidate = 'analyze'
            elif changed & {'mode', 'style', 'prompt', 'max_duration', 'planner', 'fx'}:
                invalidate = 'plan'
            elif changed:
                invalidate = 'render'
            if invalidate:
                self.invalidate(job, invalidate)
            if target != 'render' and 'analyze' not in job['completed'] and 'plan' in job['completed']:
                self.invalidate(job, 'analyze')
            if 'mode' in changed and invalidate != 'analyze' and job.get('clips'):
                job['_local_replan'] = True
            job['options'].update(options)
            if custom_plan is not None and custom_plan != job['edit_plan']:
                self.invalidate(job, 'render')
                job['edit_plan'] = custom_plan
                if 'plan' not in job['completed']:
                    job['completed'].append('plan')
            if target in ('plan', 'render') and not job['clips'] and custom_plan is None and 'analyze' in job['completed']:
                raise Conflict('No clips to plan; analyze again with different options')
            job.update(status='queued', target=target, error=None, progress=0)
            self.store.save(job)
            # Holding the lock prevents the worker from finishing before registration.
            future = self.pool.submit(self.run, job_id)
            self.active[job_id] = future
            return future

    def invalidate(self, job, stage):
        index = self.STAGES.index(stage)
        job['completed'] = [s for s in job['completed'] if s not in self.STAGES[index:]]
        if index == 0:
            job['clips'], job['candidates'] = None, []
            for field in ('_analysis_source', '_chunks', 'audio_signals', 'vjepa_signals',
                          'game', 'game_confidence', 'profile_prompt', 'window_scores', 'interest_curve', '_local_replan'):
                job.pop(field, None)
        if index <= 1:
            job['edit_plan'] = None
            job.pop('planner_plan', None)
        job['output'] = None
        for field in ('share_kit', 'team_candidates', 'team_alignments'):
            job.pop(field, None)

    def cancel(self, job_id):
        with self.lock:
            job = self.store.get(job_id)
            job.update(status='cancelled', error=None)
            self.store.save(job)
            self.keys.pop(job_id, None)
            return job

    def run(self, job_id):
        started = time.monotonic()
        try:
            with self.lock:
                job = self.store.get(job_id)
            stages = self.STAGES[:self.STAGES.index(job['target']) + 1]
            for stage in stages:
                with self.lock:
                    job = self.store.get(job_id)
                    if job['status'] == 'cancelled':
                        return
                    if stage in job['completed']:
                        continue
                    # A supplied plan can render without calling an analysis provider.
                    if stage == 'analyze' and 'plan' in job['completed']:
                        continue
                    job.update(status={'analyze': 'analyzing', 'plan': 'planning', 'render': 'rendering'}[stage],
                               stage=stage, progress=self.STAGES.index(stage) / 3)
                    self.store.save(job)
                def report(snapshot):
                    # Persist progress without checkpointing partially completed work.
                    with self.lock:
                        current = self.store.get(job_id)
                        if current['status'] != 'cancelled':
                            for field in ('pipeline_stage', 'timings', 'warnings'):
                                if field in snapshot:
                                    current[field] = snapshot[field]
                            self.store.save(current)
                if stage == 'render':
                    plan_valid(job['edit_plan'], job['meta']['duration'], job['options'].get('max_duration', 180))
                if hasattr(self.pipeline, 'run_stage'):
                    self.pipeline.run_stage(stage, job, self.keys.get(job_id), report)
                else:
                    getattr(self.pipeline, stage)(job, self.keys.get(job_id))
                if stage == 'plan':
                    plan_valid(job['edit_plan'], job['meta']['duration'], job['options'].get('max_duration', 180))
                with self.lock:
                    if self.store.get(job_id)['status'] == 'cancelled':
                        if stage == 'render' and job.get('output'):
                            Path(job['output']).unlink(missing_ok=True)
                        return
                    job['completed'].append(stage)
                    job['elapsed'] = round(time.monotonic() - started, 2)
                    self.store.save(job)
            with self.lock:
                job = self.store.get(job_id)
                if job['status'] != 'cancelled':
                    job.update(status={'analyze': 'analyzed', 'plan': 'planned', 'render': 'done'}[job['target']], progress=1)
                    self.store.save(job)
        except Exception as exc:
            # Provider exceptions can embed credentials/URLs. Persist only the type.
            with self.lock:
                job = self.store.get(job_id)
                if job['status'] != 'cancelled':
                    from services.provider_errors import ProviderFailure
                    message = str(exc) if isinstance(exc, ProviderFailure) else f'{job.get("stage", "job")} failed ({type(exc).__name__}); check configuration and retry'
                    job.update(status='error', error=message)
                    self.store.save(job)
        finally:
            with self.lock:
                directory = Path(self.store.get(job_id)['dir'])
                for segment in directory.glob('seg_*_source.mp4'):
                    segment.unlink(missing_ok=True)
                for name in ('render_tmp', 'extensions_tmp'):
                    shutil.rmtree(directory / name, ignore_errors=True)
                if self.store.get(job_id)['status'] in ('error', 'cancelled'):
                    (directory / 'output.mp4').unlink(missing_ok=True)
                self.active.pop(job_id, None)

    def close(self):
        self.stop_retention.set()
        if self.retention_thread:
            self.retention_thread.join(timeout=5)
        self.pool.shutdown(wait=True)
        self.keys.clear()
        if self.lease:
            self.lease.close()
