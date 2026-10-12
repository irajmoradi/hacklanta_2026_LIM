"""Offline Discord/API tests: no gateway connection and no provider calls."""
import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from discord_bot.core import BotError, Config, MontageService, Options, Source, select_source, share_title


@pytest.fixture
def config():
    return Config("test-token", frozenset({123}), public_url="https://clips.example",
                  vod_hosts=frozenset({"videos.example"}), poll_seconds=.001)


@pytest.fixture
def attachment():
    return SimpleNamespace(filename="game.mp4", size=10, url="https://cdn.discordapp.com/attachments/video.mp4")


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("options", [Options(mode="wrong"), Options(preset="square"), Options(length=0),
                                     Options(length=True), Options(length=3601), Options(game="x" * 101)])
def test_bad_options(options):
    with pytest.raises(BotError):
        options.validate()


def test_source_selection(config, attachment):
    assert select_source(config, attachment).filename == "game.mp4"
    assert select_source(config, url="https://videos.example/own.mp4").filename == "vod.mp4"
    for args in ({}, {"attachment": attachment, "url": "https://videos.example/a"},
                 {"url": "https://localhost/a"}, {"url": "http://videos.example/a"},
                 {"url": "https://user:password@videos.example/a"}, {"url": "https://videos.example:444/a"}):
        with pytest.raises(BotError):
            select_source(config, **args)
    attachment.size = config.max_input + 1
    with pytest.raises(BotError):
        select_source(config, attachment)


def fake_api(fits=True):
    api = SimpleNamespace(fetch_source=AsyncMock(), upload=AsyncMock(return_value={"id": "abc"}),
                          action=AsyncMock(), snapshot=AsyncMock(side_effect=[
                              {"status": "analyzing", "progress": .1},
                              {"status": "analyzing", "progress": .1},
                              {"status": "planned", "progress": .6},
                              {"status": "rendering", "progress": .7},
                              {"status": "done", "progress": 1, "share_kit": {"title": "Epic clutch"}},
                          ]), download=AsyncMock(return_value=fits))
    return api


def fake_sink():
    return SimpleNamespace(send_status=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())), deliver=AsyncMock())


@pytest.mark.parametrize("fits", [True, False])
def test_workflow_progress_and_fallback(config, fits):
    api, sink = fake_api(fits), fake_sink()
    service = MontageService(config, api)
    run(service.run(7, 123, Source("https://videos.example/a", "a.mp4"), Options("mean", "vertical", "Halo", 30), sink, 50))
    assert sink.send_status.await_count == 1
    edits = [c.kwargs["content"] for c in sink.send_status.return_value.edit.await_args_list]
    assert edits.count("Montage: analyzing (10%)") == 1
    assert "Montage: rendering (70%)" in edits
    assert edits[-1] == "Montage ready!"
    assert api.action.await_args_list[0].args == ("abc", "analyze", {"mode": "mean", "max_duration": 30, "prompt": "Gameplay context: Halo"})
    assert api.action.await_args_list[1].args == ("abc", "render", {"preset": "vertical", "generate_thumbnails": False})
    assert api.download.await_args.args[2] == 50
    text, path, link = sink.deliver.await_args.args
    assert "Epic clutch" in text
    assert (path is not None) == fits
    assert link == "https://clips.example/api/jobs/abc/download"
    assert not api.fetch_source.await_args.args[1].parent.exists()
    assert not service.active


def test_cooldown_and_channel_gate(config):
    api, sink = fake_api(), fake_sink()
    service = MontageService(config, api, clock=lambda: 100)
    source = Source("https://videos.example/a", "a.mp4")
    async def scenario():
        await service.run(7, 999, source, Options(), sink)
        api.upload.assert_not_awaited()
        await service.run(7, 123, source, Options(), sink)
        await service.run(7, 123, source, Options(), sink)
        assert "cooldown" in sink.send_status.await_args.args[0]
        assert api.upload.await_count == 1
        service.clock = lambda: 100 + config.cooldown
        api.snapshot.side_effect = [{"status": "planned"}, {"status": "done"}]
        await service.run(7, 123, source, Options(), sink)
        assert api.upload.await_count == 2
    run(scenario())


def test_active_lock_outlasts_cooldown(config):
    api, sink = fake_api(), fake_sink()
    service = MontageService(config, api)
    service.active.add(7)
    run(service.run(7, 123, Source("url", "a.mp4"), Options(), sink))
    api.upload.assert_not_awaited()


@pytest.mark.parametrize("failure", ["error", "cancelled", "timeout", "exception"])
def test_failure_cleanup(config, failure):
    api, sink = fake_api(), fake_sink()
    if failure == "timeout":
        config = replace(config, timeout=.01)
        async def slow(*args):
            await asyncio.sleep(10)
        api.snapshot.side_effect = slow
    elif failure == "exception":
        api.snapshot.side_effect = RuntimeError("secret-token")
    else:
        api.snapshot.side_effect = [{"status": failure, "error": "secret-token"}]
    service = MontageService(config, api)
    run(service.run(7, 123, Source("url", "a.mp4"), Options(), sink))
    assert api.action.await_args.args == ("abc", "cancel", {})
    assert "secret-token" not in str(sink.send_status.return_value.edit.await_args_list)
    sink.deliver.assert_not_awaited()
    assert not service.active


def test_title_fallback():
    assert share_title({}, Options(game="Halo")) == "Halo — Highlights"
    assert share_title({}, Options(mode="mean")) == "Gameplay — Funny fails"


def test_env_validation(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "not-a-real-secret")
    monkeypatch.setenv("DISCORD_ALLOWED_CHANNEL_IDS", "123,456")
    config = Config.from_env()
    assert config.channels == {123, 456}
    assert "not-a-real-secret" not in repr(config)
    monkeypatch.setenv("DISCORD_POLL_SECONDS", "nan")
    with pytest.raises(BotError):
        Config.from_env()


def test_discord_command_and_messages(config, attachment):
    pytest.importorskip("discord")
    from discord_bot.bot import MontageClient
    async def scenario():
        client = MontageClient(config, fake_api())
        client.service.run = AsyncMock()
        interaction = SimpleNamespace(channel_id=123, guild=SimpleNamespace(filesize_limit=12345),
                                      user=SimpleNamespace(id=7), channel=Mock(),
                                      response=SimpleNamespace(send_message=AsyncMock()))
        command = client.tree.get_command("montage")
        assert [c.value for c in next(p for p in command.parameters if p.name == "mode").choices] == ["nice", "mean"]
        await command.callback(interaction, video=attachment, mode="mean", preset="vertical", game="Halo", length=20)
        args = client.service.run.await_args.args
        assert args[:2] == (7, 123)
        assert args[3] == Options("mean", "vertical", "Halo", 20)
        interaction.response.send_message.assert_awaited_once()
        message = SimpleNamespace(author=SimpleNamespace(id=9, bot=False), guild=interaction.guild,
                                  channel=SimpleNamespace(id=123, send=AsyncMock()), attachments=[attachment], content="")
        await client.on_message(message)
        assert client.service.run.await_count == 2
        message.attachments = []
        message.content = "https://videos.example/my-vod.mp4"
        await client.on_message(message)
        assert client.service.run.await_count == 3
        message.author.bot = True
        await client.on_message(message)
        assert client.service.run.await_count == 3
        interaction.channel_id = 999
        await command.callback(interaction, video=attachment)
        assert client.service.run.await_count == 3
        assert interaction.response.send_message.await_args.kwargs["ephemeral"]
    run(scenario())


def test_discord_oversize_fallback(config):
    discord = pytest.importorskip("discord")
    from discord_bot.bot import ChannelSink
    channel = SimpleNamespace(send=AsyncMock())
    run(ChannelSink(channel).deliver("Share-kit title: Hello @everyone", None, "https://clips.example/a_b"))
    args = channel.send.await_args
    assert "Download: https://clips.example/a_b" in args.args[0]
    assert args.kwargs["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()


def test_discord_rejected_upload_falls_back(tmp_path):
    discord = pytest.importorskip("discord")
    from discord_bot.bot import ChannelSink
    path = tmp_path / "montage.mp4"
    path.write_bytes(b"mock video")
    error = discord.HTTPException(SimpleNamespace(status=413, reason="Too large"), {"code": 40005, "message": "Too large"})
    channel = SimpleNamespace(send=AsyncMock(side_effect=[error, None]))
    run(ChannelSink(channel).deliver("Share-kit title: Clutch", path, "https://clips.example/a"))
    assert channel.send.await_count == 2
    assert "file" in channel.send.await_args_list[0].kwargs
    assert "Download: https://clips.example/a" in channel.send.await_args.args[0]


class Response:
    def __init__(self, chunks=(), length=None, status=200, payload=None):
        self.status, self.content_length, self.payload = status, length, payload
        self.content = self
        self.chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk

    async def json(self):
        return self.payload


@pytest.mark.parametrize("length,chunks,fits", [(100, [], False), (None, [b"123", b"456"], False),
                                               (None, [b"12", b"34"], True)])
def test_bounded_http(config, tmp_path, length, chunks, fits):
    pytest.importorskip("aiohttp")
    from discord_bot.api import JobAPI
    api = JobAPI(config)
    session = SimpleNamespace(get=Mock(return_value=Response(chunks, length)))
    assert run(api.transfer(session, "https://videos.example/a", tmp_path / "a.mp4", 4)) == fits
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_http_routes_and_multipart(config, tmp_path):
    pytest.importorskip("aiohttp")
    from discord_bot.api import JobAPI
    api = JobAPI(config)
    response = Response(payload={"id": "abc"})
    api.session = SimpleNamespace(post=Mock(return_value=response), get=Mock(return_value=response))
    path = tmp_path / "game.mp4"
    path.write_bytes(b"mock video")
    async def scenario():
        assert await api.upload(path) == {"id": "abc"}
        form = api.session.post.call_args.kwargs["data"]
        assert form._fields[0][0]["name"] == "video"
        assert form._fields[0][0]["filename"] == "game.mp4"
        await api.action("abc", "analyze", Options().analysis())
        assert api.session.post.call_args.args[0].endswith("/api/jobs/abc/analyze")
        assert api.session.post.call_args.kwargs["json"]["max_duration"] == 60
        await api.snapshot("abc")
        assert api.session.get.call_args.args[0].endswith("/api/jobs/abc")
    run(scenario())


def test_redirect_and_private_ip_rejected(config, tmp_path, monkeypatch):
    aiohttp = pytest.importorskip("aiohttp")
    from discord_bot.api import JobAPI, PublicResolver
    api = JobAPI(config)
    session = SimpleNamespace(get=Mock(return_value=Response(status=302)))
    with pytest.raises(BotError):
        run(api.transfer(session, "https://videos.example/a", tmp_path / "a", 10))
    with pytest.raises(BotError):
        run(api.fetch_source("https://127.0.0.1/a", tmp_path / "a", 10))
    monkeypatch.setattr(aiohttp.resolver.DefaultResolver, "resolve", AsyncMock(return_value=[{"host": "127.0.0.1"}]))
    async def scenario():
        resolver = PublicResolver()
        try:
            with pytest.raises(BotError):
                await resolver.resolve("videos.example", 443)
        finally:
            await resolver.close()
    run(scenario())


def test_real_job_api_contract_with_synthetic_video(config, tmp_path, video):
    """Exercise real Flask validation/queue with a mocked paid/render pipeline."""
    from server.api import create_app
    calls = []

    def analyze(job, key):
        calls.append("analyze")
        assert job["options"]["mode"] == "mean"
        assert job["options"]["prompt"] == "Gameplay context: Halo"
        job["clips"] = [{"id": "0", "start_seconds": 0, "end_seconds": 1}]

    def plan(job, key):
        calls.append("plan")
        job["edit_plan"] = {"segments": [{"source_start": 0, "source_end": 1}]}

    def render(job, key):
        calls.append("render")
        assert job["options"]["preset"] == "vertical"
        assert job["options"]["generate_thumbnails"] is False
        output = Path(job["dir"]) / "output.mp4"
        output.write_bytes(Path(job["source"]).read_bytes())
        job["output"] = str(output)

    app = create_app({"TESTING": True, "WORKSPACE": str(tmp_path / "workspace")},
                     SimpleNamespace(analyze=analyze, plan=plan, render=render))
    client = app.test_client()

    class FlaskAPI:
        async def fetch_source(self, url, path, limit):
            path.write_bytes(video.read_bytes())

        async def upload(self, path):
            with path.open("rb") as stream:
                response = client.post("/api/jobs", data={"video": (stream, path.name)})
            assert response.status_code == 201
            return response.json

        async def action(self, job_id, action, payload):
            response = client.post(f"/api/jobs/{job_id}/{action}", json=payload)
            assert response.status_code == 202
            return response.json

        async def snapshot(self, job_id):
            return client.get(f"/api/jobs/{job_id}").json

        async def download(self, job_id, path, limit):
            response = client.get(f"/api/jobs/{job_id}/download")
            try:
                assert response.status_code == 200
                path.write_bytes(response.data)
            finally:
                response.close()
            return True

    sink = fake_sink()
    try:
        run(MontageService(replace(config, timeout=10), FlaskAPI()).run(
            7, 123, Source("unused", "game.mp4"), Options("mean", "vertical", "Halo", 30), sink))
        assert calls == ["analyze", "plan", "render"]
        sink.deliver.assert_awaited_once()
        assert sink.send_status.return_value.edit.await_args.kwargs["content"] == "Montage ready!"
    finally:
        app.extensions["job_queue"].close()
