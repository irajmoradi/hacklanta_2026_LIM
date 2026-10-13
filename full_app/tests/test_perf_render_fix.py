from concurrent.futures import ThreadPoolExecutor
import threading

from perf.cache import Cache


def test_different_cache_keys_build_concurrently(tmp_path):
    cache = Cache(tmp_path)
    barrier = threading.Barrier(2)
    def get(key):
        def build(output):
            barrier.wait(timeout=5)
            output.write_text(key)
        return cache.get('test', [], key, '.txt', build)
    with ThreadPoolExecutor(2) as pool:
        outputs = list(pool.map(get, ['a', 'b']))
    assert [p.read_text() for p in outputs] == ['a', 'b']
