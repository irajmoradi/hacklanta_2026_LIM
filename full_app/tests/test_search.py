"""Synthetic library search contracts. No models, media, or paid calls required."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from search import SearchIndex, SearchWindow, create_blueprint
from search.embeddings import LocalSentenceEncoder


def window(window_id="ace", **kwargs):
    values = dict(video_id="video-a", window_id=window_id, start=10.5, end=20,
                  game="Valorant", recorded_at="2026-10-10T14:00:00Z",
                  caption="Jett ace wins the round", labels=["highlight", "ace"],
                  media_url="/media/video-a.mp4", thumbnail_url="/thumbs/video-a-ace.jpg")
    values.update(kwargs)
    return SearchWindow(**values)


@pytest.fixture
def library(tmp_path):
    index = SearchIndex(tmp_path / "search.sqlite3")
    index.index_windows([
        window(),
        window("jett", caption="Jett buys a rifle", labels=["neutral"], start=30, end=40),
        window("death", caption="I died to the Operator", labels=["lowlight", "death"],
               ocr_events=[{"text": "Operator", "kind": "death", "time": 51}], start=50, end=60),
        window("funny", game="Overwatch2", caption="Funny moments with Lance",
               labels=["funny"], transcript="Lance: banana squad assemble!", recorded_at="2026-10-11T23:59:59Z"),
        window("ocr", caption="HUD event", labels=["neutral"], ocr_events=[{"text": "PENTAKILL"}],
               recorded_at="2026-10-12T00:00:00Z"),
    ])
    return index


@pytest.mark.parametrize("query,expected", [("my Jett ace", "ace"),
    ("every time I died to the Operator", "death"), ("funny moments with Lance", "funny"),
    ("banana squad", "funny"), ("pentakill", "ocr"), ("lowlight", "death")])
def test_ranking_and_all_signals(library, query, expected):
    result = library.search(query)
    assert result["mode"] == "bm25"
    assert result["results"][0]["window_id"] == expected
    assert result["results"][0]["score"] > 0


def test_filters_dates_and_browse(library):
    assert library.search("Jett", game="VALORANT", labels=["ACE", "highlight"])["total"] == 1
    assert library.search("Jett", game="Overwatch2")["total"] == 0
    assert library.search("", labels=["high"])["total"] == 0  # exact labels
    result = library.search("", date_from="2026-10-11", date_to="2026-10-11")
    assert [r["window_id"] for r in result["results"]] == ["funny"]
    assert library.search("", date_from="2026-10-12T01:59:59+02:00", date_to="2026-10-11")["total"] == 1
    assert library.search("", date_to="2026-10-11T23:59:59Z")["total"] == 4
    assert library.search("Valorant")["total"] == 4
    assert library.search("")["results"][0]["window_id"] == "ocr"


def test_links_and_pagination(library):
    result = library.search("ace")["results"][0]
    assert result["thumbnail_url"] == "/thumbs/video-a-ace.jpg"
    assert result["jump_url"] == "/media/video-a.mp4#t=10.5,20"
    assert result["start"] == 10.5 and result["end"] == 20
    all_results = library.search("Jett")["results"]
    assert library.search("Jett", limit=1, offset=1)["results"] == all_results[1:2]
    assert library.search("Jett", offset=20)["total"] == 2


@pytest.mark.parametrize("query", ['" OR NOT * (', "NEAR(foo bar)", "'; DROP TABLE windows;--", "😀", "my every time", ""])
def test_arbitrary_query_is_not_fts_syntax(library, query):
    library.search(query)
    assert library.search("ace")["total"] == 1


def test_atomic_replacement_idempotency_and_delete(library):
    library.index_windows([window(caption="Sage resurrection", labels=["support"])])
    assert library.search("ace")["total"] == 0
    assert library.search("", labels=["ace"])["total"] == 0
    assert library.search("Sage")["total"] == 1
    with pytest.raises(ValueError):
        library.index_windows([window(), window("bad", end=1)], replace_video="video-a")
    assert library.search("")["total"] == 5
    with pytest.raises(ValueError):
        library.index_windows([window(video_id="other")], replace_video="video-a")
    library.index_windows([window()], replace_video="video-a")
    assert library.search("")["total"] == 1
    library.index_windows([window(video_id="other")])
    library.index_windows([], replace_video="video-a")
    assert library.search("ace")["total"] == 1
    assert library.delete_video("other") == 1
    assert library.search("ace")["total"] == 0
    with sqlite3.connect(library.path) as db:
        assert db.execute("SELECT count(*) FROM window_fts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM labels").fetchone()[0] == 0


def test_reopen_and_concurrent_requests(library):
    reopened = SearchIndex(library.path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reopened.search("ace")["total"], range(12)))
    assert results == [1] * 12


@pytest.mark.parametrize("kwargs", [dict(start=-1), dict(end=float("nan")), dict(start=True),
    dict(labels="ace"), dict(recorded_at="yesterday"), dict(media_url="javascript:alert(1)"),
    dict(thumbnail_url="//evil.test/image"), dict(media_url="/\\evil.test"), dict(ocr_events={})])
def test_window_validation(library, kwargs):
    with pytest.raises(ValueError):
        library.index_windows([window(**kwargs)])
    assert library.search("")["total"] == 5


@pytest.mark.parametrize("kwargs", [dict(limit=0), dict(offset=-1), dict(limit=101), dict(query="x"*1001),
    dict(date_from="bad"), dict(date_from="2026-10-12", date_to="2026-10-11"), dict(labels="ace")])
def test_query_validation(library, kwargs):
    with pytest.raises(ValueError):
        library.search(**kwargs)


class FakeEncoder:
    model_id = "synthetic-v1"

    def encode(self, texts):
        return [[1, 0] if any(word in text.casefold() for word in ("ace", "flawless")) else [0, 1] for text in texts]


def test_semantic_retrieval_filters_and_model_identity(tmp_path):
    index = SearchIndex(tmp_path / "hybrid.sqlite3", encoder=FakeEncoder())
    index.index_windows([window(), window("other", caption="Shopping for equipment", labels=["neutral"])])
    assert index.search("flawless")["results"][0]["window_id"] == "ace"
    assert index.search("flawless")["mode"] == "hybrid"
    assert index.search("flawless", labels=["neutral"])["total"] == 0
    assert index.search("flawless", game="Overwatch2")["total"] == 0
    assert index.search("flawless", date_from="2026-10-11")["total"] == 0
    assert index.search("ace")["results"][0]["window_id"] == "ace"
    index.encoder.model_id = "synthetic-v2"
    assert index.search("flawless")["total"] == 0
    assert index.search("ace")["mode"] == "bm25"
    assert SearchIndex(index.path).search("ace")["total"] == 1


@pytest.mark.parametrize("failure", [ImportError("optional dependency absent"), RuntimeError("missing local weights"), None])
def test_encoder_failure_falls_back(library, failure):
    class BrokenEncoder:
        model_id = "broken"

        def encode(self, texts):
            if failure:
                raise failure
            return [[float("nan")]] * len(texts)

    library.encoder = BrokenEncoder()
    library.index_windows([window()])
    assert library.search("my Jett ace")["results"][0]["window_id"] == "ace"
    assert library.search("ace")["mode"] == "bm25"


def test_local_model_is_lazy_and_offline(monkeypatch):
    from types import SimpleNamespace
    calls = []

    def model(name, **kwargs):
        calls.append((name, kwargs))
        raise RuntimeError("weights unavailable")

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=model))
    encoder = LocalSentenceEncoder("/models/pinned-mini-model")
    assert calls == []
    with pytest.raises(RuntimeError):
        encoder.encode(["test"])
    assert calls == [("/models/pinned-mini-model", {"local_files_only": True, "device": "cpu"})]


def test_flask_endpoint(library):
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(library))
    client = app.test_client()
    response = client.get("/api/search?q=my+Jett+ace&game=valorant&label=ace&label=highlight")
    assert response.status_code == 200
    assert response.json["total"] == 1
    assert response.json["results"][0]["jump_url"].endswith("#t=10.5,20")
    assert client.get("/api/search?date_from=2026-10-11&date_to=2026-10-11").json["total"] == 1
    for query in ("limit=oops", "limit=101", "offset=-1", "date_from=wrong", "label=", "game="):
        invalid = client.get("/api/search?" + query)
        assert invalid.status_code == 400
        assert "error" in invalid.json
    assert client.post("/api/search").status_code == 405
