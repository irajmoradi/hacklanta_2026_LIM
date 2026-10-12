from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import time

from flask import Flask
from PIL import Image
import pytest

from sharepage import ShareStore, create_blueprint


@pytest.fixture
def assets(video, tmp_path):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (160, 120), "navy").save(poster)
    return dict(video_path=video, poster_path=poster, title="Last-second win",
                description="A clutch & a laugh", width=160, height=120,
                chapters=[{"start": 2, "title": "Final play"}, {"start": 0, "title": "Opening"}])


def app_for(store):
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(create_blueprint(store))
    return app


@pytest.fixture
def setup(tmp_path, assets):
    store = ShareStore(tmp_path / "shares.sqlite3")
    return store, store.create(**assets), app_for(store).test_client()


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize("dimensions", [(1920, 1080), (1080, 1920)])
def test_page_metadata_chapters_and_assets(setup, assets, dimensions):
    store, _, client = setup
    share_id = store.create(**(assets | dict(width=dimensions[0], height=dimensions[1])))
    response = client.get(f"/s/{share_id}", base_url="https://clips.example")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    tags = Tags(html).tags
    meta = {attrs.get("property", attrs.get("name")): attrs.get("content")
            for tag, attrs in tags if tag == "meta"}
    assert meta["og:title"] == assets["title"]
    assert meta["og:description"] == assets["description"]
    assert meta["og:url"] == f"https://clips.example/s/{share_id}"
    assert meta["og:image"] == f"https://clips.example/s/{share_id}/poster"
    assert meta["og:video"] == f"https://clips.example/s/{share_id}/video"
    assert meta["twitter:card"] == "summary_large_image"
    assert meta["twitter:image"] == meta["og:image"]
    player = next(attrs for tag, attrs in tags if tag == "video")
    assert player["width"] == str(dimensions[0])
    assert player["height"] == str(dimensions[1])
    assert "playsinline" in player and "controls" in player
    assert player["poster"] == meta["og:image"]
    starts = [attrs["data-start"] for _, attrs in tags if "data-start" in attrs]
    assert starts == ["0.0", "2.0"]
    assert "no-store" in response.headers["Cache-Control"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    for tag, attrs in tags:
        if tag == "script" or (tag == "link" and attrs.get("rel") == "stylesheet"):
            assert client.get(attrs.get("src", attrs.get("href"))).status_code == 200
    poster = client.get(f"/s/{share_id}/poster")
    assert poster.mimetype == "image/jpeg"
    assert poster.data == assets["poster_path"].read_bytes()
    partial = client.get(f"/s/{share_id}/video", headers={"Range": "bytes=0-31"})
    assert partial.status_code == 206
    assert partial.data == assets["video_path"].read_bytes()[:32]


def react(client, share_id, emoji="🔥", **kwargs):
    return client.post(f"/s/{share_id}/reactions", json={"emoji": emoji},
                       headers={"X-Sharepage-Reaction": "1", **kwargs})


def test_reactions_persist_across_app_restart(setup):
    store, share_id, client = setup
    assert react(client, share_id).json["counts"]["🔥"] == 1
    restarted = ShareStore(store.database)
    other_client = app_for(restarted).test_client()
    assert react(other_client, share_id).json["counts"]["🔥"] == 2
    assert react(other_client, share_id, "😂").json["counts"]["😂"] == 1
    html = other_client.get(f"/s/{share_id}").get_data(as_text=True)
    assert '<span class="count">2</span>' in html


def test_concurrent_reactions_do_not_lose_counts(setup):
    store, share_id, _ = setup
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(lambda _: store.react(share_id, "👏"), range(40)))
    assert store.counts(share_id)["👏"] == 40


def test_expiry_covers_page_media_and_reactions(setup, assets, monkeypatch):
    store, _, client = setup
    deadline = time.time() + 60
    share_id = store.create(**assets, expires_at=deadline)
    assert client.get(f"/s/{share_id}").status_code == 200
    monkeypatch.setattr("sharepage.store.time.time", lambda: deadline)
    for suffix in ("", "/video", "/poster"):
        response = client.get(f"/s/{share_id}{suffix}")
        assert response.status_code == 404
        assert response.headers["Cache-Control"] == "no-store"
    assert react(client, share_id).status_code == 404
    assert not store.react(share_id, "🔥")
    assert store.counts(share_id)["🔥"] == 0


def test_invalid_ids_missing_assets_and_unpredictable_ids(setup, assets):
    store, share_id, client = setup
    assert len(share_id) == 43
    assert len({store.create(**assets) for _ in range(50)}) == 50
    for missing in ("unknown", "A" * 43, "..", "x' OR 1=1"):
        assert client.get(f"/s/{missing}").status_code == 404
        assert react(client, missing).status_code == 404
    assets["poster_path"].unlink()
    assert client.get(f"/s/{share_id}/poster").status_code == 404


def test_escape_untrusted_metadata(setup, assets):
    store, _, client = setup
    attack = '<script>alert("x")</script>'
    share_id = store.create(**(assets | dict(title=attack, description=attack,
                                            chapters=[dict(start=1, title=attack)])))
    html = client.get(f"/s/{share_id}").get_data(as_text=True)
    assert attack not in html
    assert "&lt;script&gt;" in html


def test_reaction_validation_and_cross_origin_protection(setup):
    store, share_id, client = setup
    route = f"/s/{share_id}/reactions"
    assert react(client, share_id, "not-emoji").status_code == 400
    assert react(client, share_id, Origin="https://attacker.example").status_code == 403
    assert client.post(route, json={"emoji": "🔥"}).status_code == 403
    assert react(client, share_id, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    for body in ([], None, {"emoji": ["🔥"]}, {"emoji": "x" * 2000}):
        response = client.post(route, json=body, headers={"X-Sharepage-Reaction": "1"})
        assert response.status_code in (400, 413)
    assert store.counts(share_id)["🔥"] == 0


@pytest.mark.parametrize("changes", [dict(title=""), dict(width=0), dict(height=True),
    dict(expires_at=float("nan")), dict(chapters=[dict(start=-1, title="bad")]),
    dict(chapters=[dict(start=float("inf"), title="bad")]), dict(description="x" * 2001)])
def test_creation_validation(setup, assets, changes):
    store, _, _ = setup
    with pytest.raises(ValueError):
        store.create(**(assets | changes))
