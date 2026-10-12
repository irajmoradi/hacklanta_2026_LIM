import json
import sys
from types import SimpleNamespace

import pytest

from ingest import IngestError
from ingest.chat import chat_signal, twitch_messages


def test_twitch_json_bins_spikes_and_clip_mentions(tmp_path):
    path = tmp_path / "chat.json"
    path.write_text(json.dumps({"comments": [
        {"content_offset_seconds": 0.2, "message": {"body": "hello"}},
        {"content_offset_seconds": 2.1, "message": {"body": "PogChamp LUL KEKW clip it!"}},
        {"content_offset_seconds": 2.8, "message": {"fragments": [{"text": "Pog clip that"}]}},
        {"content_offset_seconds": -1, "message": {"body": "LUL"}},
        {"content_offset_seconds": 4, "message": {"body": "LUL"}},
        {"content_offset_seconds": "nan", "message": "ignored"},
        {"message": "missing time"}, None,
    ]}), encoding="utf-8")
    rows = chat_signal(path, 4)
    assert len(rows) == 4
    assert [r["signals"]["chat_activity"] for r in rows] == [1, 0, 2, 0]
    assert rows[2]["signals"]["chat_emotes"] == 4
    assert rows[2]["signals"]["chat_clip_it"] == 2
    assert rows[2]["signals"]["chat_emote_spike"] == pytest.approx(3**0.5)
    assert rows[1]["signals"]["chat_emote_spike"] == 0
    assert "hello" not in json.dumps(rows)


def test_chat_downloader_format_offset_empty_and_boundaries():
    rows = chat_signal([
        {"time_in_seconds": 100.3, "message": "kekw CLIP THIS"},
        {"time_in_seconds": 101.2, "message": "PogChampionship eclipse itinerary"},
        {"time_in_seconds": 102, "message": "LUL"},
    ], 1.5, offset=-100)
    assert rows[0]["signals"]["chat_clip_it"] == 1
    assert rows[1]["end"] == 1.5
    assert rows[1]["signals"]["chat_emotes"] == 0
    assert all(all(value == 0 for value in row["signals"].values())
               for row in chat_signal([], 3))
    with pytest.raises(IngestError):
        chat_signal({}, 3)
    with pytest.raises(IngestError):
        chat_signal([], 3, offset=float("nan"))


def test_optional_vod_fetch_mocked_and_closed(monkeypatch):
    calls = []

    class Downloader:
        def get_chat(self, url, **kwargs):
            calls.append((url, kwargs))
            return iter([{"time_in_seconds": 10.5, "message": "LUL clipit"}])

        def close(self):
            calls.append("closed")

    monkeypatch.setitem(sys.modules, "chat_downloader", SimpleNamespace(ChatDownloader=Downloader))
    rows = chat_signal(twitch_messages("1234", 2, offset=-10), 2, offset=-10)
    assert rows[0]["signals"]["chat_activity"] == 1
    assert calls[0][0] == "https://www.twitch.tv/videos/1234"
    assert calls[0][1]["start_time"] == 10
    assert calls[0][1]["end_time"] == 12
    assert calls[-1] == "closed"
    monkeypatch.setitem(sys.modules, "chat_downloader", None)
    with pytest.raises(IngestError, match="optional chat-downloader"):
        list(twitch_messages("1234", 2))
    with pytest.raises(IngestError, match="digits"):
        list(twitch_messages("bad/id", 2))
