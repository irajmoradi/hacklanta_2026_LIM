"""POLISH-1 regressions; synthetic media and mocked providers only."""
from itertools import combinations
import json
import subprocess

import pytest
from PIL import Image

from cards.rendering import compose_card, install_cards
from pipeline.ranking import rank_merge
from planner import plan_edit
from render.engine import Renderer
from render.plan import RenderPlan, Segment
from render.text_layout import editorial_text, overlaps, resolve_segment, strip_descriptions
from services.ffmpeg_runner import FFmpegRunner


def test_signal_metadata_never_becomes_display_copy():
    assert rank_merge([dict(start=0, end=2)], [], [])[0]['description'] == ''
    assert editorial_text('Signal candidate') == ''
    assert editorial_text('Default caption') == ''
    assert editorial_text('Phoenix ults and aggressively pushes through the smoke to secure multiple kills.') == ''
    assert editorial_text('he did NOT see that') == 'he did NOT see that'
    source = 'Phoenix pushes smoke'
    planned = plan_edit([dict(id='a', start=0, end=4, score=.9, label='highlight',
                             caption=source, signals=dict(kill_time=2))], target_length=4)
    assert all(t.content != source and len(t.content.split()) <= 5 for t in planned.text)
    saved = dict(segments=[dict(title=source, texts=[dict(content=source)])])
    strip_descriptions(saved, [source])
    assert saved == dict(segments=[dict(texts=[])])


@pytest.mark.parametrize('preset', ['landscape', 'vertical', 'square'])
def test_every_frame_has_disjoint_text_boxes(preset):
    segment = Segment(source_start=0, source_end=6, title='Signal candidate',
        texts=[dict(start=0, duration=5, content='Phoenix aggressively pushes through the smoke.'),
               dict(start=0, duration=2, content='SMOKE PUSH', position='center'),
               dict(start=0, duration=2, content='CLEAN PICK'),
               dict(start=3, duration=2, content='NEXT ROUND')],
        timed_effects=[dict(name=n, start=0, duration=2) for n in
                       ['pop_no_shot', 'banner_eliminated', 'fail_arrow']],
        reactions=[dict(start=3, duration=1, label='hype')])
    boxes = resolve_segment(segment, preset)
    assert segment.title is None
    assert len(segment.timed_effects) == 1  # other text FX collide with the pop
    assert [t.content for t in segment.texts] == ['SMOKE PUSH']
    for frame in range(180):
        active = [b for b in boxes if b['start'] <= frame/30 < b['end']]
        assert all(not overlaps(a, b) for a, b in combinations(active, 2))
    # Adjacent events may occupy the same zone without losing either.
    segment = Segment(source_start=0, source_end=2, texts=[
        dict(start=i, duration=1, content='CLEAN PICK') for i in (0, 1)])
    assert len(resolve_segment(segment, preset)) == 2


def test_speech_preserved_and_colliding_editorial_omitted():
    segment = Segment(source_start=0, source_end=3,
        words=[dict(start=0, end=1, text='Actual speech is allowed more than five words')],
        texts=[dict(start=0, duration=1, content='CLEAN PICK')])
    boxes = resolve_segment(segment, 'vertical')
    assert len(segment.words) == 1 and not segment.texts
    assert boxes[0]['kind'] == 'speech'


def test_hitmarker_does_not_displace_editorial_word_pop():
    segment = Segment(source_start=0, source_end=3, timed_effects=[
        dict(name=name, start=1, duration=1) for name in ('hitmarker_cyan', 'pop_no_shot')])
    boxes = resolve_segment(segment, 'landscape')
    assert len(segment.timed_effects) == 2
    assert [b['content'] for b in boxes] == ['pop_no_shot']


def test_crossfade_outgoing_reaction_cannot_cover_incoming_speech(video, tmp_path):
    engine = Renderer(FFmpegRunner(tmp_path/'work', video, 160, 120, 10))
    plan = RenderPlan(resolution=720, fps=10, transition='flash', transition_duration=.2,
        captions=dict(enabled=True), segments=[
            dict(source_start=0, source_end=1,
                 reactions=[dict(start=.5, duration=.5, label='hype')]),
            dict(source_start=1, source_end=2,
                 words=[dict(start=0, end=.5, text="Someone's")])])
    engine.render(plan)
    boxes = [dict(box, start=box['start']+timing['start'], end=box['end']+timing['start'])
             for i, timing in enumerate(engine.segment_timeline) for box in engine.text_boxes[i]]
    assert all(not overlaps(a, b) for a, b in combinations(boxes, 2))
    assert engine.executed_plan.segments[0].reactions[0].duration == pytest.approx(.3)
    assert engine.executed_plan.segments[1].words[0].start == pytest.approx(.2)
    assert plan.segments[1].words[0].start == 0  # original saved plan is unchanged


@pytest.mark.parametrize('copy', ['Signal candidate', 'Phoenix aggressively pushes the smoke and gets several kills'])
def test_refiner_cannot_reintroduce_descriptions_or_labels(copy):
    from planner.refinement import refine_captions
    plan = plan_edit([dict(id='a', start=0, end=4, score=.9, label='highlight',
                          signals=dict(kill_time=2))], target_length=4)
    result = refine_captions(plan, lambda _: dict(captions=[dict(text_index=0, content=copy)]))
    assert result.text == plan.text
    assert 'failed validation' in result.notes[-1]


@pytest.mark.parametrize('size', [(320, 180), (180, 320), (240, 240)])
def test_cached_card_fills_each_aspect_without_black_bars(tmp_path, size):
    source = tmp_path/'card.png'
    Image.new('RGB', (320, 180), '#ea8632').save(source)
    result = compose_card(source, tmp_path/'composed.png', size)
    with Image.open(result) as image:
        assert image.size == size
        assert all(min(image.getpixel(point)) > 20 for point in
                   [(0, 0), (size[0]-1, size[1]-1), (size[0]//2, 0)])


@pytest.mark.parametrize('preset', ['vertical', 'square'])
def test_encoded_cards_fill_frame_and_saved_labels_are_removed(video, tmp_path, preset):
    art = tmp_path/'art.png'
    Image.new('RGB', (320, 180), '#ea8632').save(art)
    renderer = install_cards(Renderer, {'intro': art})
    engine = renderer(FFmpegRunner(tmp_path/'work', video, 160, 90, 10))
    output = engine.render(RenderPlan(preset=preset, resolution=720, fps=10,
        intro=dict(text='INTRO', duration=.5), captions=dict(enabled=True),
        segments=[dict(source_start=0, source_end=1, title='Signal candidate',
            texts=[dict(start=0, duration=1, content='Phoenix aggressively pushes through the smoke.')])]))
    assert not engine.caption_events
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '0.1', '-i', str(output),
        '-frames:v', '1', '-vf', 'scale=16:16', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    assert min(raw) > 15
    assert all('pad=' not in graph for graph in engine.filter_graphs if 'zoompan' in graph)


def test_deadlock_style_provider_failure_remains_cached(video, tmp_path):
    from cards import generate_cards
    from tests.test_cards import FakeImageClient, job_for
    job = job_for(video, tmp_path)
    client = FakeImageClient(fail=True)
    assets = generate_cards(job, video, job['edit_plan']['segments'], lambda: client, job['warnings'].append)
    assert json.loads((tmp_path/'cards/outro.json').read_text())['reason'] == 'provider'
    job['options']['preset'] = 'vertical'
    generate_cards(job, video, job['edit_plan']['segments'], lambda: pytest.fail('cached failure retried'),
                   job['warnings'].append)
    compose_card(assets['outro'], tmp_path/'vertical.png', (180, 320))
    assert len(client.calls) == 2
    assert any('cached local fish/car' in w for w in job['warnings'])
