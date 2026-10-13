"""Card-inclusive caps, with provider-free synthetic render regression coverage."""
import copy
import pytest

from pipeline.experience import budget_duration
from render.plan import RenderPlan
from test_cards import FakeImageClient, job_for
from pipeline import Pipeline
from services.probe import probe_video


def test_beat_snap_trims_late_sound_and_caption_before_encode(video, tmp_path):
    job = job_for(video, tmp_path)
    job['options'].update(ai_cards=False, cards=False, music=True, beat_sync=True,
                          captions=True, max_duration=3)
    job['edit_plan'].update(music=dict(path=str(video), beats=[.8], beat_sync=True))
    job['edit_plan']['segments'] = [dict(source_start=0, source_end=1,
        sound_effects=[dict(sfx_key='cinematic_boom', offset_in_segment=.9, duration=.1)],
        texts=[dict(start=.1, duration=.9, content='A complete phrase')]),
        dict(source_start=2, source_end=3)]
    Pipeline().render(job, None)
    segment = job['render_plan']['segments'][0]
    assert not segment['sound_effects']
    assert not segment['texts']  # snapped below the 0.75-second readability floor
    assert probe_video(job['output'])['duration'] <= 2.1


def test_budget_drops_single_word_and_trimmed_editorial_flashes():
    plan = dict(segments=[dict(source_start=0, source_end=10, texts=[
        dict(start=9, duration=1, content='GG!'),
        dict(start=0, duration=1, content='A complete phrase'),
        dict(start=1, duration=1, content='A readable phrase')])])
    result = budget_duration(plan, 9)
    assert [t['content'] for t in result['segments'][0]['texts']] == ['A readable phrase']
    assert all(len(t['content'].split()) > 1 for t in budget_duration(plan, None)['segments'][0]['texts'])


@pytest.mark.parametrize('maximum', [1, 3, 30, 45, 60])
@pytest.mark.parametrize('transition', ['cut', 'varied'])
def test_budget_caps_cards_and_validates_local_events(maximum, transition):
    segment = dict(source_start=0, source_end=10, speed=.5,
        timed_effects=[dict(name='damage_pulse', start=9, duration=.4)],
        texts=[dict(start=0, duration=20, content='A complete caption')],
        reactions=[dict(start=9, duration=1, label='hype')],
        words=[dict(start=9, end=10, text='hello')],
        sound_effects=[dict(sfx_key='cinematic_boom', offset_in_segment=9, duration=1)],
        fx=[dict(name='zoom_punch', start=9, end=10)],
        sam=dict(subject_track=[dict(time=9, x=.5)]))
    plan = dict(render_version=2, fps=30, transition=transition,
        intro=dict(text='Intro', duration=3.5), outro=dict(text='Outro', duration=3.5),
        segments=[copy.deepcopy(segment) for _ in range(4)])
    original = copy.deepcopy(plan)
    result = RenderPlan.model_validate(budget_duration(plan, maximum))
    assert plan == original
    assert sum(round(s.duration*30)/30 for s in result.segments) + sum(
        round(c.duration*30)/30 for c in (result.intro, result.outro)) <= maximum+1e-8
    assert result.segments[0].source_start >= 0
    assert all(s.source_end <= 10 for s in result.segments)


@pytest.mark.parametrize('ai_cards', [False, True])
@pytest.mark.parametrize('transition', ['cut', 'varied'])
def test_actual_media_includes_cards_inside_cap(video, tmp_path, monkeypatch, ai_cards, transition):
    job = job_for(video, tmp_path)
    job['options'].update(max_duration=3, ai_cards=ai_cards, full_experience=True,
                          reactions=False, transitions=transition != 'cut')
    job['edit_plan']['transition'] = transition
    pipeline, client = Pipeline(), FakeImageClient()
    monkeypatch.setattr(pipeline, 'client', lambda *args: client)
    pipeline.render(job, None)
    assert probe_video(job['output'])['duration'] <= 3.05
    assert job['render_plan']['intro'] and job['render_plan']['outro']
    assert len(client.calls) == (2 if ai_cards else 0)
