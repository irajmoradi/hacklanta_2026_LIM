"""Queue-owned chat edits, durable versions, and undo."""
from copy import deepcopy
from .queue import Conflict


def apply_result(queue, job, result):
    if result['fallback'] and job.get('edit_plan') is None and result['plan'] is not None:
        job['edit_plan'] = result['plan']
        if 'plan' not in job['completed']:
            job['completed'].append('plan')
    if not result['fallback']:
        versions = job.setdefault('agent_versions', [])
        versions.append(dict(plan=deepcopy(job['edit_plan']), options=deepcopy(job['options'])))
        del versions[:-20]
        queue.invalidate(job, 'render')
        job['edit_plan'] = result['plan']
        job['options'].update(result['settings'])
        if 'plan' not in job['completed']:
            job['completed'].append('plan')
    job['agent_result'] = result
    job['agent_trace'] = result['trace']
    job['agent_version'] = job.get('agent_version', 0) + (not result['fallback'])


def run(queue, job, instruction, model_factory=None, max_steps=16, call_limit=None):
    from editor_agent import run_agent
    def emit(step):
        queue.store.append_event(job['id'], 'agent_step', step)
    def cancelled():
        return queue.store.get(job['id'])['status'] == 'cancelled'
    model = model_factory() if model_factory else None
    try:
        return run_agent(job, instruction, model, max_steps=max_steps, call_limit=call_limit,
                         emit=emit, cancelled=cancelled)
    finally:
        if model is not None and hasattr(model, 'close'):
            model.close()


def submit(queue, job_id, instruction, model_factory=None, max_steps=8, call_limit=None):
    with queue.lock:
        job = queue.store.get(job_id)
        if job_id in queue.active:
            raise Conflict('Job is busy')
        if len(queue.active) >= queue.capacity:
            raise Conflict('Queue is full; retry later')
        if not job.get('edit_plan') and not job.get('clips'):
            raise Conflict('Analyze before editing')
        previous_status = job['status']
        job.update(status='editing', stage='agent', error=None)
        queue.store.save(job)
        def worker():
            try:
                result = run(queue, job, instruction, model_factory, max_steps, call_limit)
                with queue.lock:
                    if queue.store.get(job_id)['status'] == 'cancelled':
                        return dict(result, fallback=True, reason='cancelled', plan=job['edit_plan'])
                    apply_result(queue, job, result)
                    status = previous_status if result['fallback'] else 'planned'
                    if job.get('edit_plan') and previous_status == 'analyzed':
                        status = 'planned'
                    job.update(status=status, stage='agent')
                    queue.store.save(job)
                    return dict(result, version=job.get('agent_version', 0))
            finally:
                with queue.lock:
                    current = queue.store.get(job_id)
                    if current['status'] == 'editing':
                        current.update(status=previous_status, error='Agent failed; starting plan retained')
                        queue.store.save(current)
                    queue.active.pop(job_id, None)
        future = queue.pool.submit(worker)
        queue.active[job_id] = future
        return future


def undo(queue, job_id):
    with queue.lock:
        job = queue.store.get(job_id)
        if job_id in queue.active:
            raise Conflict('Job is busy')
        versions = job.get('agent_versions', [])
        if not versions:
            raise Conflict('No previous agent plan')
        previous = versions.pop()
        queue.invalidate(job, 'render')
        job['edit_plan'], job['options'] = previous['plan'], previous['options']
        job['agent_version'] = job.get('agent_version', 0) + 1
        job.update(status='planned' if job['edit_plan'] else 'analyzed', stage='agent')
        if job['edit_plan'] is None:
            job['completed'] = [s for s in job['completed'] if s != 'plan']
        step = dict(tool='undo', args={}, rationale='Restore previous plan version',
                    diff={'plan': {'after': job['edit_plan']}}, error=None)
        job['agent_trace'] = [step]
        job.pop('agent_result', None)
        queue.store.save(job)
        queue.store.append_event(job_id, 'agent_step', step)
        return dict(plan=job['edit_plan'], trace=[step], version=job['agent_version'])
