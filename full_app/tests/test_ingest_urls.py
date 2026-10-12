import sys
from types import SimpleNamespace

import pytest

from ingest import IngestError, Limits, prepare
from ingest import media
from ingest.urls import download


@pytest.fixture
def fake_ytdlp(monkeypatch):
    state = {"info": {"duration": 2, "filesize": 3}, "payload": b"vod", "calls": []}

    class YoutubeDL:
        def __init__(self, options):
            state["options"] = self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=False):
            assert download is False
            state["calls"].append("metadata")
            return state["info"]

        def process_ie_result(self, info, download=True):
            state["calls"].append("download")
            self.options["match_filter"](info)
            for event in state.get("events", [{"filename": "video", "status": "finished",
                                               "downloaded_bytes": len(state["payload"])}]):
                self.options["progress_hooks"][0](event)
            from pathlib import Path
            Path(self.options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(state["payload"])
            return info

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=YoutubeDL))
    return state


def test_url_mock_download_and_progress(tmp_path, fake_ytdlp):
    events = []
    result = download("https://youtu.be/owned", tmp_path, limits=Limits(),
                      owns_content=True, progress=events.append)
    assert result.read_bytes() == b"vod"
    assert fake_ytdlp["calls"] == ["metadata", "download"]
    assert events[-1]["downloaded_bytes"] == 3
    assert fake_ytdlp["options"]["noplaylist"] is True


@pytest.mark.parametrize("info, message", [
    ({"duration": 999}, "max_duration"),
    ({"duration": 2, "filesize": 1000}, "max_bytes"),
    ({"duration": None}, "known finite"),
    ({"duration": float("inf")}, "duration"),
    ({"duration": 2, "is_live": True}, "finite VODs"),
    ({"entries": []}, "single VOD"),
    ({"duration": 2, "requested_formats": [{"filesize": 60}, {"filesize": 60}]}, "max_bytes"),
])
def test_preflight_limits(tmp_path, fake_ytdlp, info, message):
    fake_ytdlp["info"] = info
    with pytest.raises(IngestError, match=message):
        download("https://www.twitch.tv/videos/1234", tmp_path,
                 limits=Limits(max_bytes=100, max_duration=10), owns_content=True)
    assert fake_ytdlp["calls"] == ["metadata"]


def test_download_cumulative_limit(tmp_path, fake_ytdlp):
    fake_ytdlp["info"] = {"duration": 2}
    fake_ytdlp["events"] = [{"filename": "video", "downloaded_bytes": 60},
                           {"filename": "audio", "downloaded_bytes": 60}]
    with pytest.raises(IngestError, match="max_bytes"):
        download("https://youtu.be/owned", tmp_path,
                 limits=Limits(max_bytes=100), owns_content=True)


@pytest.mark.parametrize("url", ["https://youtube.com.evil.test/foo", "http://youtu.be/foo",
                                "https://localhost/foo", "https://user:pass@youtu.be/foo"])
def test_unsupported_urls(tmp_path, url):
    with pytest.raises(IngestError, match="Only HTTPS"):
        download(url, tmp_path, limits=Limits(), owns_content=True)


def test_missing_extra_and_rights(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    with pytest.raises(IngestError, match="owns_content"):
        download("https://youtu.be/owned", tmp_path, limits=Limits(), owns_content=False)
    with pytest.raises(IngestError, match="optional yt-dlp"):
        download("https://youtu.be/owned", tmp_path, limits=Limits(), owns_content=True)


def test_prepare_url_mocked_end_to_end_and_cleanup(tmp_path, fake_ytdlp):
    video = tmp_path / "generated.mp4"
    media.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
               "testsrc2=size=160x90:rate=30:duration=1", "-c:v", "libx264", str(video)])
    fake_ytdlp["payload"] = video.read_bytes()
    cache = tmp_path / "cache"
    result = prepare("https://youtu.be/owned", owns_content=True, cache_dir=cache,
                     chat_log=[{"time_in_seconds": 0.5, "message": "PogChamp"}])
    assert result.path.exists() and result.proxy.exists()
    assert result.chat_signal[0]["signals"]["chat_emotes"] == 1
    assert not list(cache.glob("download-*"))
    fake_ytdlp["info"] = {"duration": 999999}
    with pytest.raises(IngestError):
        prepare("https://youtu.be/owned", owns_content=True, cache_dir=cache)
    assert not list(cache.glob("download-*"))
