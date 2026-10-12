import subprocess
from types import SimpleNamespace
import pytest

from models.effects import VIDEO_EFFECTS
from render.placements import effects_graph
from render.audio import sfx_graph
from render.plan import Sound, TimedEffect


@pytest.mark.parametrize('name', sorted(VIDEO_EFFECTS.keys()-{'none','slow_motion','speed_2x'}))
def test_every_registered_timed_effect_runs(name):
    # Late placement catches legacy text gates; rendering catches unsupported filters.
    graph = '[0:v]null[placement_input]'+effects_graph(
        [TimedEffect(name=name, start=2.1, duration=.3)], (160,90), 20, 2.5)
    if name.startswith('text_'):
        assert "between(t,0,2)" not in graph
    subprocess.run(['ffmpeg','-v','error','-filter_complex_threads','1','-f','lavfi','-i',
                    'testsrc2=s=160x90:r=20:d=2.5','-filter_complex',graph,
                    '-map','[v]','-t','2.5','-f','null','-'], check=True, capture_output=True)


def test_all_overlapping_sounds_are_mixed_and_ducked(tmp_path):
    sounds = [Sound(sfx_key=n, offset_in_segment=.2, duration=.5, gain=.3+i*.1)
              for i,n in enumerate(['bass_drop','anime_wow','another_one','impact_hit','taco_bell'])]
    args, graph = sfx_graph(sounds, 1, 1)
    assert 'amix=inputs=6' in graph and 'normalize=0' in graph and 'alimiter=' in graph
    assert "volume='if(gt(" in graph
    assert graph.count('adelay=200') == 5
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=400:duration=1',
                    *args,'-filter_complex','[0:a]anull[baseaudio]'+graph,'-map','[outa]',
                    '-t','1',str(tmp_path/'mixed.wav')], check=True, capture_output=True)


def test_unknown_sound_is_not_silently_skipped():
    with pytest.raises(ValueError, match='Unknown'):
        sfx_graph([Sound(sfx_key='missing')],1,1)


def test_final_master_leaves_aac_headroom(tmp_path):
    import array
    from render.audio import master_audio
    source = tmp_path/'loud.mkv'
    output = tmp_path/'mastered.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=20:d=1',
                    '-f','lavfi','-i','sine=frequency=400:duration=1','-af','volume=16',
                    '-c:v','libx264','-c:a','pcm_f32le','-ac','2',str(source)],check=True,capture_output=True)
    master_audio(source,output)
    raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vn','-f','f32le','-'])
    samples = array.array('f')
    samples.frombytes(raw)
    assert .7 < max(abs(s) for s in samples) < 1
    # Mastering must not re-encode or alter a video frame.
    def video_hash(path):
        return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v','-c','copy','-f','hash','-'])
    assert video_hash(source) == video_hash(output)
