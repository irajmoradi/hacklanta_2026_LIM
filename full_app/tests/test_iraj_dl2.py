"""Owner controls: no implicit narrator and no unselected reaction faces."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pipeline.extensions import team_source
from reactions.pack import Reaction, ReactionSelector, configure_render_speakers
from server.capabilities import frontend_capabilities
from server.legacy import EDIT_STYLES
from server.validation import options_valid


@pytest.fixture
def pack(tmp_path, monkeypatch):
    (tmp_path / 'clip.mp4').touch()
    entries = [dict(id=f'{speaker}-{label}', speaker=speaker, label=label,
                    text=label, file='clip.mp4', duration=1, background='opaque')
               for speaker in ('Iraj', 'Alex', 'Lance') for label in ('hype', 'bruh', 'clutch')]
    (tmp_path / 'pack.json').write_text(json.dumps({'clips': entries}))
    monkeypatch.setenv('REACTION_PACK', str(tmp_path))
    return [Reaction(**{**r, 'file': tmp_path / r['file']}) for r in entries]


def test_options_and_capabilities(pack):
    assert options_valid({'full_experience': True}, EDIT_STYLES)['narration'] is False
    assert options_valid({'full_experience': True, 'narration': True,
                          'narration_persona': 'nature_documentary'}, EDIT_STYLES)['narration'] is True
    for speakers in ([], ['Iraj'], ['Iraj', 'Alex']):
        assert options_valid({'reaction_speakers': speakers}, EDIT_STYLES)['reaction_speakers'] == speakers
    assert options_valid({'reaction_speakers': ['Iraj', 'Iraj']}, EDIT_STYLES)['reaction_speakers'] == ['Iraj']
    capabilities = frontend_capabilities()
    assert capabilities['reaction_speakers'] == ['Alex', 'Iraj', 'Lance']
    assert 'reaction_speakers' in capabilities['options']


@pytest.mark.parametrize('value', [None, 'Iraj', {}, [1], [''], ['iraj'], ['Missing'], ['Iraj'] * 101])
def test_invalid_speakers(pack, value):
    with pytest.raises(ValueError, match='reaction_speakers'):
        options_valid({'reaction_speakers': value}, EDIT_STYLES)


@pytest.mark.parametrize('mode', ['nice', 'mean'])
@pytest.mark.parametrize('speakers', [[], ['Iraj'], ['Iraj', 'Alex'], ['Missing']])
def test_rotation_never_escapes_filter(pack, speakers, mode):
    selector = ReactionSelector(pack, seed=7, cover_speakers=True, reaction_speakers=speakers)
    selected = [selector.select(label, mode=mode) for label in ['hype', 'bruh', 'clutch'] * 4]
    if speakers == ['Missing']:
        assert selected == [None] * 12
        return
    assert {r.speaker for r in selected} == set(speakers or ['Iraj', 'Alex', 'Lance'])
    assert len({r.label for r in selected}) > 1
    assert all(a.id != b.id for a, b in zip(selected, selected[1:]))


def test_scope_is_consumed_explicit_override_and_failure_cleanup(pack, tmp_path):
    scratch = tmp_path / 'render'
    scratch.mkdir()
    team_source(None, {'options': {'reaction_speakers': ['Iraj']}}, scratch)
    assert {r.speaker for r in ReactionSelector(pack).reactions} == {'Iraj'}
    assert len(ReactionSelector(pack).reactions) == len(pack)
    configure_render_speakers(['Iraj'], scratch)
    assert len(ReactionSelector(pack, reaction_speakers=[]).reactions) == len(pack)
    configure_render_speakers(['Iraj'], scratch)
    scratch.rmdir()  # render_job's finally also runs on failures
    assert len(ReactionSelector(pack).reactions) == len(pack)


def test_concurrent_job_filters(pack, tmp_path):
    def select(speaker):
        configure_render_speakers([speaker], tmp_path)
        return ReactionSelector(pack).select().speaker
    with ThreadPoolExecutor(max_workers=3) as workers:
        assert list(workers.map(select, ['Iraj', 'Alex', 'Lance'] * 10)) == ['Iraj', 'Alex', 'Lance'] * 10


def test_no_pack_advertises_no_names(monkeypatch):
    monkeypatch.delenv('REACTION_PACK', raising=False)
    assert frontend_capabilities()['reaction_speakers'] == []
    assert options_valid({'reaction_speakers': []}, EDIT_STYLES)['reaction_speakers'] == []
