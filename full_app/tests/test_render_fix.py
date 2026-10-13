"""Regression coverage for isolation limits, overlay order and segment scheduling."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import numpy as np
import pytest

from render.engine import Renderer, probe
from render.plan import RenderPlan, Word
from services.ffmpeg_runner import FFmpegRunner


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=s=320x180:r=30:d=2', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000:duration=2',
                    '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', str(path)], check=True)
    return path


@pytest.mark.skipif(sys.platform != 'linux', reason='production Linux resource limits')
def test_six_landscape_segments_and_cards_under_worker_limits(source, tmp_path):
    # Limit is inherited by ffmpeg, exactly as in server.stage_worker.
    code = '''
import resource, sys
resource.setrlimit(resource.RLIMIT_AS, (8*1024**3, 8*1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE, (4*1024**3, 4*1024**3))
from pathlib import Path
from render.engine import Renderer, probe
from render.plan import RenderPlan
from services.ffmpeg_runner import FFmpegRunner
plan = RenderPlan(segments=[dict(source_start=0, source_end=1) for _ in range(6)],
    resolution=1080, transition='varied', transition_duration=.1,
    intro=dict(text='INTRO', duration=.5), outro=dict(text='OUTRO', duration=.5))
renderer = Renderer(FFmpegRunner(Path(sys.argv[2]), Path(sys.argv[1]), *plan.size, plan.fps))
output = renderer.render(plan)
info = probe(output)
assert abs(float(info['format']['duration']) - 6.3) < .11, info
video, audio = info['streams'][:2]
assert (video['width'], video['height']) == (1920, 1080)
assert abs(float(video['duration'])-float(audio['duration'])) < .11
joins = [g for g in renderer.filter_graphs if 'xfade=' in g]
assert len(joins) == 7 and all(g.count('xfade=') == 1 for g in joins)
'''
    result = subprocess.run([sys.executable, '-c', code, str(source), str(tmp_path/'limited')],
                            env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'},
                            capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('name', ['text_rip', 'pop_bruh', 'banner_skill_issue'])
def test_text_appears_and_expires_during_freeze(source, tmp_path, name):
    # Text starts after the frame freeze starts and ends before the hold ends.
    # Compare decoded pixels against a matching freeze without text.
    frames = []
    for text in (False, True):
        effects = [dict(name='freeze', start=.2, duration=1.4)]
        if text:
            effects.insert(0, dict(name=name, start=.6, duration=.5))
        plan = RenderPlan(resolution=720, segments=[dict(source_start=0, source_end=2,
            timed_effects=effects)])
        engine = Renderer(FFmpegRunner(tmp_path / str(text), source, *plan.size, 30))
        output = engine.render(plan)
        samples = []
        for at in (.4, .8, 1.3):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(output),
                '-frames:v', '1', '-vf', 'scale=320:180', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                check=True, capture_output=True).stdout
            samples.append(np.frombuffer(raw, np.uint8).astype(float))
        frames.append(samples)
    differences = [np.abs(a-b).mean() for a, b in zip(*frames)]
    assert differences[1] > 1.5, differences
    assert differences[0] < differences[1] / 3, differences
    assert differences[2] < differences[1] / 3, differences


def test_prepared_processors_overlap_and_keep_order(source, tmp_path, monkeypatch):
    from perf.encoders import Encoder
    monkeypatch.setattr('perf.encoders.best', lambda **kw: Encoder())
    monkeypatch.setattr('perf.parallel.worker_count', lambda *a, **kw: 2)
    rendezvous = threading.Barrier(2)
    prepared, completed, directories = [], [], set()
    class Processor:
        def prepare(self, index, segment, duration):
            prepared.append(index)
            def process(path, i, segment, duration, directory):
                rendezvous.wait(timeout=30)
                completed.append(i)
                directories.add(directory)
                return path, duration
            return process
    plan = RenderPlan(resolution=720, segments=[dict(source_start=0, source_end=.4)]*2)
    renderer = Renderer(FFmpegRunner(tmp_path/'parallel', source, *plan.size, 30), Processor())
    output = renderer.render(plan)
    assert prepared == [0, 1] and sorted(completed) == [0, 1]
    assert len(directories) == 2
    assert abs(float(probe(output)['format']['duration']) - .8) < .11


def test_transcription_burns_in_first_encode(source, tmp_path, monkeypatch):
    seen = []
    def transcribe(path, model):
        assert probe(path)['streams'][0]['codec_type'] == 'audio'
        return [Word(start=.1, end=.3, text='HELLO')]
    monkeypatch.setattr('render.engine.transcribe', transcribe)
    engine = Renderer(FFmpegRunner(tmp_path/'captions', source, 1280, 720, 30))
    encode = engine.encode
    def tracked(args, output, directory):
        seen.append((args, output))
        return encode(args, output, directory)
    monkeypatch.setattr(engine, 'encode', tracked)
    engine.render(RenderPlan(resolution=720, captions=dict(enabled=True, transcribe=True),
                             segments=[dict(source_start=0, source_end=.5)]))
    segments = [(args, path) for args, path in seen if path.name.startswith('clip_')]
    assert len(segments) == 1 and 'ass=' in segments[0][0][segments[0][0].index('-filter_complex')+1]
    assert not any(path.name.startswith('captioned_') for _, path in seen)
    assert engine.caption_events[0]['text'] == 'HELLO'


def test_renderer_errors_are_render_category(tmp_path, monkeypatch):
    from render.contracts import RenderFailure
    engine = Renderer(FFmpegRunner(tmp_path, tmp_path/'missing', 1280, 720, 30, perf=False))
    with pytest.raises(RenderFailure) as caught:
        engine.render(RenderPlan(segments=[dict(source_start=0, source_end=1)]))
    assert caught.value.category == caught.value.code == 'render'
    assert 'Gemini' not in str(caught.value)
    from services.provider_errors import classify, ProviderFailure
    transported = ProviderFailure(classify(caught.value).code)
    assert transported.code == 'render' and 'Gemini' not in str(transported)


def test_prepared_overlay_shares_segment_encode(source, tmp_path):
    class Overlay:
        def compose(self, args, graph, **context):
            assert context['cache'] is not None
            graph = graph.replace('[outv]', '[before_overlay]')
            graph += ';[before_overlay]drawbox=x=0:y=0:w=100:h=100:c=red:t=fill[outv]'
            return args, graph
    class Processor:
        def prepare(self, index, segment, duration):
            return Overlay()
    renderer = Renderer(FFmpegRunner(tmp_path/'overlay', source, 1280, 720, 30), Processor())
    renderer.render(RenderPlan(resolution=720, captions=dict(enabled=True), segments=[
        dict(source_start=0, source_end=.5, words=[dict(start=0, end=.4, text='ONE PASS')])]))
    graphs = [g for g in renderer.filter_graphs if 'ass=' in g]
    assert len(graphs) == 1 and 'drawbox=' in graphs[0]


@pytest.mark.skipif(sys.platform != 'linux', reason='production worker')
def test_worker_transports_render_failure(tmp_path):
    job = dict(dir=str(tmp_path), source=str(tmp_path/'missing.mp4'),
               meta=dict(width=1280, height=720, fps=30), clips=[], warnings=[],
               edit_plan=dict(render_version=2, segments=[dict(source_start=0, source_end=1)]),
               options=dict(privacy=False, reactions=False, captions=False, sam=False))
    payload = dict(stage='render', job=job, key=None, memory=8*1024**3, file_bytes=4*1024**3)
    result = subprocess.run([sys.executable, '-m', 'server.stage_worker'],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'_stage_error': 'render'}
