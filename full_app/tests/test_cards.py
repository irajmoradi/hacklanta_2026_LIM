"""FISH-1 synthetic-media tests; image generation is always fake."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from cards import generate_cards, install_cards
from cards.generation import prompt_for
from pipeline import Pipeline
from services.probe import probe_video


class FakeImageClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def generate_thumbnail(self, frame, prompt, output, *, image_budget):
        image_budget.reserve()
        self.calls.append((frame, prompt))
        if self.fail:
            raise RuntimeError('secret must never escape')
        shutil.copyfile(frame, output)
        return output


def job_for(video, directory):
    return dict(id='fish-test', source=str(video), dir=str(directory), warnings=[],
                options=dict(ai_cards=True, cards=True, captions=False, mode='mean'),
                meta=probe_video(video), title='THE MOST CORNY CLUTCH',
                clips=[dict(start_seconds=2, end_seconds=3, score=.9)],
                edit_plan=dict(render_version=2, resolution=720, fps=10, segments=[
                    dict(source_start=0, source_end=1), dict(source_start=2, source_end=3)]))


@pytest.mark.parametrize('fail', [False, True])
def test_generation_cache_and_warning(video, tmp_path, fail):
    job = job_for(video, tmp_path)
    client = FakeImageClient(fail)
    assets = generate_cards(job, video, job['edit_plan']['segments'], lambda: client,
                            job['warnings'].append, top_index=1)
    assert len(client.calls) == 2
    assert 'THE MOST CORNY CLUTCH' in client.calls[0][1]
    assert all(word in client.calls[1][1] for word in ('fish', 'THANKS FOR WATCHING', 'AIMED BETTER'))
    for path in assets.values():
        with Image.open(path) as image:
            image.verify()
    # Cache persists even with a fresh job object/provider and repeats warnings.
    fresh = job_for(video, tmp_path)
    def forbidden():
        pytest.fail('cache must not open a client')
    assert generate_cards(fresh, video, fresh['edit_plan']['segments'], forbidden,
                          fresh['warnings'].append) == assets
    assert bool(fresh['warnings']) == fail
    assert 'secret' not in str(job['warnings'])
    assert json.loads((tmp_path / 'cards/outro.json').read_text())['fallback'] == fail


def test_missing_client_and_interrupted_attempt(video, tmp_path):
    job = job_for(video, tmp_path)
    def unavailable():
        raise ValueError('no key')
    generate_cards(job, video, job['edit_plan']['segments'], unavailable, job['warnings'].append)
    assert len(job['warnings']) == 2
    (tmp_path / 'cards/intro.png').unlink()
    client = FakeImageClient()
    generate_cards(job, video, job['edit_plan']['segments'], lambda: client, job['warnings'].append)
    assert not client.calls


def test_pipeline_timeline_music_and_top_frame(video, tmp_path, monkeypatch):
    pipeline, client = Pipeline(), FakeImageClient()
    monkeypatch.setattr(pipeline, 'client', lambda *args: client)
    job = job_for(video, tmp_path)
    music = tmp_path / 'music.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'sine=frequency=200:duration=1', str(music)], check=True)
    job['edit_plan']['music'] = dict(path=str(music), beat_sync=False)
    pipeline.render(job, None)
    assert len(client.calls) == 2
    assert job['render_evidence']['timeline'] == [dict(start=3.5, duration=1), dict(start=4.5, duration=1)]
    assert probe_video(job['output'])['duration'] == pytest.approx(9, abs=.15)
    assert any('zoompan' in graph for graph in job['render_evidence']['filter_graphs'])
    assert any('amix' in graph for graph in job['render_evidence']['filter_graphs'])
    # Intro reference is the highest-ranked selected clip; outro is the last.
    assert (tmp_path / 'cards/intro_frame.png').read_bytes() == (tmp_path / 'cards/outro_frame.png').read_bytes()


def test_plain_cards_remain_opt_out(video, tmp_path, monkeypatch):
    pipeline = Pipeline()
    monkeypatch.setattr(pipeline, 'client', lambda *args: pytest.fail('plain card opened provider'))
    job = job_for(video, tmp_path)
    job['options'].update(ai_cards=False, full_experience=True)
    pipeline.render(job, None)
    assert not (tmp_path / 'cards').exists()
    assert job['render_plan']['intro']['duration'] == 1


def test_full_default_and_prompt_variety():
    import random
    from pipeline.experience import FULL_EXPERIENCE
    assert FULL_EXPERIENCE['ai_cards'] is True
    prompts = {prompt_for('outro', 'TITLE', 'nice', random.Random(i)) for i in range(15)}
    assert len(prompts) > 3
    assert all('fish' in p and 'THANKS FOR WATCHING' in p for p in prompts)
