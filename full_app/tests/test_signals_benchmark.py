"""Opt-in real decode benchmark; no API calls or downloaded media.

RUN_SIGNALS_BENCHMARK=1 python -m pytest tests/test_signals_benchmark.py -s -q
"""

import os
import subprocess
import time

import pytest

from signals import detect_candidates


@pytest.mark.skipif(os.environ.get("RUN_SIGNALS_BENCHMARK") != "1",
                    reason="opt-in ten-minute 1080p benchmark")
def test_ten_minute_1080p(tmp_path):
    # Limit the process and its decoder children to at most 12 available cores.
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, set(sorted(affinity)[:12]))
    try:
        segment = tmp_path / "segment.mp4"
        video = tmp_path / "ten-minutes.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=s=1920x1080:r=30,drawbox=color=black:t=fill:enable='lt(t,2)'",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
            "-t", "5", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-threads", "8", "-c:a", "aac", str(segment),
        ], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "119", "-i",
                        str(segment), "-t", "600", "-c", "copy", str(video)],
                       check=True, capture_output=True)
        start = time.perf_counter()
        candidates = detect_candidates(video, scene_backend="ffmpeg")
        elapsed = time.perf_counter() - start
        print(f"1080p30 H.264: duration=600s cores={len(os.sched_getaffinity(0))} "
              f"elapsed={elapsed:.3f}s candidates={len(candidates)}")
        assert candidates
        assert elapsed < 60, f"detection took {elapsed:.3f}s (target <60s)"
    finally:
        os.sched_setaffinity(0, affinity)
