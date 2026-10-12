"""Offline profile contracts plus real ffmpeg/Tesseract synthetic footage."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profiles import Box, OCRToken, detect_frames, detect_game, get_profile, list_profiles, match_events
from profiles import detection


CASES = [
    ("valorant", "ACE", "announcements"),
    ("overwatch2", "ELIMINATED BY", "death_banner"),
    ("deadlock", "KILLING BLOW", "death_banner"),
    ("league_of_legends", "PENTAKILL", "announcements"),
]


def token_in(game, text, region, width=1280, height=720):
    left, top, right, bottom = get_profile(game).regions[region].pixels(width, height)
    x, y = (left+right)/2/width, (top+bottom)/2/height
    return OCRToken(text, Box(x-.01, y-.01, x+.01, y+.01))


@pytest.mark.parametrize("name", list_profiles())
def test_profile_contract(name):
    p = get_profile(name)
    assert p.name == name
    assert set(p.regions) == {"kill_feed", "death_banner", "spectating", "round_score", "announcements", "health"}
    assert set(p.keywords) == {"kill", "death", "assist", "multikill", "teamwipe", "round_won", "round_lost", "objective_taken"}
    assert all(p.keywords.values())
    assert all("?" not in phrase and "\ufffd" not in phrase for phrases in p.keywords.values() for phrase in phrases)
    assert all(getattr(p, field) for field in ["alive_rules", "dead_rules", "spectating_rules", "highlights", "lowlights", "aspect_notes"])
    assert all(weight > 0 for weight in p.signal_weights.values())
    assert "ATTRIBUTION" in p.prompt_fragment()
    assert "REACTION HINTS" in p.prompt_fragment()
    for width, height in [(1920,1080), (1920,1200), (3440,1440), (320,720)]:
        for box in p.regions.values():
            for letterboxed in (False, True):
                x1,y1,x2,y2=box.pixels(width,height,letterboxed=letterboxed)
                assert 0 <= x1 < x2 <= width
                assert 0 <= y1 < y2 <= height


def test_region_math():
    assert Box(.25,.25,.75,.75).pixels(1920,1080) == (480,270,1440,810)
    assert Box(0,0,1,1).pixels(1920,1200,letterboxed=True) == (0,60,1920,1140)
    assert Box(0,0,1,1).pixels(2560,1080,letterboxed=True) == (320,0,2240,1080)
    assert Box(0,0,.1,1,"left").pixels(2560,1080) == (0,0,192,1080)
    assert Box(.9,0,1,1,"right").pixels(2560,1080) == (2368,0,2560,1080)
    assert Box(.25,0,.75,1,"center").pixels(2560,1080) == (800,0,1760,1080)
    with pytest.raises(ValueError): Box(.8,0,.2,1)
    with pytest.raises(ValueError): Box(0,0,1,1,"bad")
    with pytest.raises(ValueError): Box(0,0,1,1).pixels(0,720)
    with pytest.raises(ValueError): get_profile("../../secrets")


@pytest.mark.parametrize("game,text,event", [
    ("valorant", "SPIKE DESARMADA!", "objective_taken"),
    ("overwatch2", "Eliminado por Fulano", "death"),
    ("overwatch2", "Ressurgirá em 5", "death"),
    ("deadlock", "INCOMING DAMAGE (LAST DEATH)", "death"),
    ("deadlock", "Urna entregue", "objective_taken"),
    ("league_of_legends", "Você foi abatido", "death"),
    ("league_of_legends", "Has sido asesinado", "death"),
    ("league_of_legends", "PENTAKILL", "teamwipe"),
    ("league_of_legends", "Dragão", "objective_taken"),
    ("generic", "Assistência", "assist"),
])
def test_multilingual_keywords(game,text,event):
    assert event in match_events(text,game)


def test_word_boundaries_and_league_rules():
    assert not match_events("placement fireplace skilled", "valorant")
    assert "no crosshair" in " ".join(get_profile("league_of_legends").alive_rules)
    assert get_profile("league_of_legends").signal_weights["motion"] < get_profile("valorant").signal_weights["motion"]


@pytest.mark.parametrize("game,text,region", CASES)
@pytest.mark.parametrize("width,height", [(1280,720),(1920,1200),(3440,1440)])
def test_detection_layout(game,text,region,width,height):
    assert detect_frames([(width,height,[token_in(game,text,region,width,height)])])[0] == game


def test_ambiguous_and_misplaced_evidence():
    assert detect_frames([]) == ("generic",0)
    assert detect_frames([(1280,720,[OCRToken("PENTAKILL",Box(0,.90,.15,.95))])]) == ("generic",0)
    tokens=[token_in("valorant","ACE","announcements"),token_in("league_of_legends","PENTAKILL","announcements")]
    assert detect_frames([(1280,720,tokens)]) == ("generic",0)
    assert detect_frames([(1280,720,[OCRToken("PENTAKILL",Box(.4,.2,.6,.3),.1)])]) == ("generic",0)


@pytest.fixture
def synthetic_video(tmp_path):
    def make(game="generic",text="",region="announcements"):
        assert shutil.which("ffmpeg"), "Linux runner requires ffmpeg"
        font=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        assert font.is_file(), "Linux runner requires DejaVu font for synthetic OCR"
        left,top,right,bottom=get_profile(game).regions[region].pixels(1280,720)
        # Broad HUD blocks and white text on a dark background, all generated here.
        filters=["drawbox=x=0:y=670:w=1280:h=50:color=gray:t=2"]
        if text:
            filters.append(f"drawtext=fontfile={font}:text='{text}':fontsize=28:fontcolor=white:x={left+8}:y={(top+bottom)//2}")
        path=tmp_path/f"{game}.mp4"
        subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=c=0x101010:s=1280x720:r=10:d=1","-vf",",".join(filters),"-c:v","libx264","-pix_fmt","yuv420p",str(path)],check=True,capture_output=True)
        return path
    return make


@pytest.mark.parametrize("game,text,region", CASES+[("valorant","KILLED BY","death_banner")])
def test_real_ocr_video(synthetic_video,game,text,region):
    assert shutil.which("tesseract"), "Linux runner requires tesseract"
    video=synthetic_video(game,text,region)
    observed=[]
    def reader(png):
        tokens=detection.tesseract_ocr(png)
        observed.extend(tokens)
        return tokens
    name,confidence=detect_game(video,sample_count=2,ocr=reader)
    assert name == game
    assert .5 < confidence <= 1
    event="teamwipe" if text in {"ACE","PENTAKILL"} else "death"
    assert event in match_events(" ".join(t.text for t in observed),game)


def test_generic_video_and_explicit_fallback(synthetic_video):
    video=synthetic_video()
    assert detect_game(video,sample_count=1) == ("generic",0)
    calls=[]
    def fallback(images):
        calls.append(images)
        assert images[0].startswith(b"\x89PNG")
        return "deadlock",.8
    assert detect_game(video,sample_count=1,ocr=lambda png:[],vlm_fallback=fallback) == ("deadlock",.8)
    assert len(calls)==1
    with pytest.raises(ValueError):
        detect_game(video,sample_count=1,ocr=lambda png:[],vlm_fallback=lambda images:("unknown",.8))
    with pytest.raises(ValueError):
        detect_game(video,sample_count=1,ocr=lambda png:[],vlm_fallback=lambda images:("deadlock",float("nan")))


def test_injected_ocr_skips_fallback(synthetic_video):
    video=synthetic_video()
    def forbidden(images):
        pytest.fail("confident local detection must not invoke fallback")
    assert detect_game(video,sample_count=1,ocr=lambda png:[token_in("league_of_legends","PENTAKILL","announcements")],vlm_fallback=forbidden)[0] == "league_of_legends"


def test_missing_tools_and_invalid_input(tmp_path,monkeypatch):
    path=tmp_path/"bad.mp4"
    path.write_bytes(b"not a video")
    assert detect_game(path) == ("generic",0)
    with pytest.raises(FileNotFoundError): detect_game(tmp_path/"missing")
    for count in [0,33,1.5,True]:
        with pytest.raises(ValueError): detect_game(path,sample_count=count)
    monkeypatch.setattr(detection.shutil,"which",lambda name:None)
    assert detect_game(path) == ("generic",0)
    assert detection.tesseract_ocr(b"") == []
