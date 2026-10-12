"""Bound subprocess concurrency and preserve timeline order, including title jobs."""
import os
from concurrent.futures import ThreadPoolExecutor
from .encoders import best


def worker_count(encoder=None, gpu_sessions=2, cores=None):
    encoder = encoder or best()
    cores = cores or os.cpu_count() or 1
    return max(1, min(4, cores // max(1, encoder.threads), gpu_sessions if encoder.hardware else cores))


def render_all(jobs, encoder=None, gpu_sessions=2):
    """Jobs are zero-argument callables. Use unique outputs; failures propagate."""
    with ThreadPoolExecutor(max_workers=worker_count(encoder, gpu_sessions)) as pool:
        return list(pool.map(lambda job: job(), jobs))
