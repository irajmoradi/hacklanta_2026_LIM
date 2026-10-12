import json
import logging
import os
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from publish import OAuth, PublishError, TikTok, TokenStore, YouTube


@pytest.fixture(scope="module")
def base_kit(tmp_path_factory):
    from social import build_share_kit
    import subprocess
    job = tmp_path_factory.mktemp("publish") / "job"
    job.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=160x120:rate=10:duration=6", "-c:v", "libx264",
                    str(job / "final_edit.mp4")], check=True, timeout=30)
    return build_share_kit(job, [{"start": 0, "end": 6, "description": "Test play"}],
                           {"segments": [{"start": 0, "end": 6}]}, "valorant")


@pytest.fixture
def kit(tmp_path, base_kit):
    import shutil
    return shutil.copytree(base_kit, tmp_path / "kit")


class Auth:
    def access_token(self):
        return "secret-access"


def adapter(cls, handler):
    return cls(Auth(), httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("cls", [YouTube, TikTok])
def test_dry_run_and_consent(kit, cls):
    def forbidden(request):
        pytest.fail("Dry run or unconfirmed upload used HTTP")
    uploader = adapter(cls, forbidden)
    preview = uploader.upload(kit)
    assert preview["dry_run"] and preview["metadata"]["title"]
    assert preview["metadata"]["thumbnail"].endswith("thumbnail_vertical.jpg")
    if cls is YouTube:
        assert preview["privacy"] == "private"
        assert "#Shorts" in preview["metadata"]["description"]
    for value in (False, "yes", 1):
        with pytest.raises(PublishError, match="confirm=True"):
            uploader.upload(kit, dry_run=False, confirm=value)


def test_youtube_chunks_recover_partial_ack(kit):
    payload = b"x" * (256 * 1024 * 2 + 42)
    (kit / "video.mp4").write_bytes(payload)
    calls = []
    def handler(req):
        calls.append(req)
        if req.url.path.endswith("thumbnails/set"):
            assert req.url.params["videoId"] == "video123"
            assert req.content == (kit / "thumbnail_vertical.jpg").read_bytes()
            return httpx.Response(200, json={"items": [{}]})
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["status"]["privacyStatus"] == "unlisted"
            assert "Shorts" in body["snippet"]["tags"]
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session"})
        position = len(calls)
        if position == 2:
            raise httpx.ReadTimeout("secret-token-in-url", request=req)
        if position == 3:
            assert req.headers["Content-Range"] == f"bytes */{len(payload)}"
            return httpx.Response(308, headers={"Range": "bytes=0-131071"})
        if position == 4:
            assert req.headers["Content-Range"].startswith("bytes 131072-393215/")
            return httpx.Response(308, headers={"Range": "bytes=0-393215"})
        assert req.content == payload[393216:]
        return httpx.Response(201, json={"id": "video123"})
    result = adapter(YouTube, handler).upload(kit, dry_run=False, confirm=True,
                                            privacy="unlisted", chunk_size=256 * 1024)
    assert result["video_id"] == "video123"
    assert result["thumbnail_status"] == "uploaded"
    assert len(calls) == 6


def test_thumbnail_failure_preserves_uploaded_video(kit):
    def handler(req):
        if req.url.path.endswith("thumbnails/set"):
            return httpx.Response(403)
        if req.method == "POST":
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/session"})
        return httpx.Response(201, json={"id": "keep-me"})
    result = adapter(YouTube, handler).upload(kit, dry_run=False, confirm=True)
    assert result["video_id"] == "keep-me"
    assert result["status"] == "uploaded"
    assert "manual" in result["thumbnail_status"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
@pytest.mark.parametrize("cls", [YouTube, TikTok])
def test_http_errors_redacted(kit, cls, status, caplog):
    caplog.set_level(logging.INFO)
    def handler(req):
        return httpx.Response(status, text="secret-access secret-refresh")
    with pytest.raises(PublishError) as error:
        adapter(cls, handler).upload(kit, dry_run=False, confirm=True)
    assert str(status) in str(error.value)
    assert "secret-access" not in str(error.value) + caplog.text


@pytest.mark.parametrize("size", [123, 10_000_123])
def test_tiktok_chunks(kit, size, caplog):
    caplog.set_level(logging.DEBUG)
    (kit / "video.mp4").write_bytes(b"x" * size)
    calls = []
    def handler(req):
        calls.append(req)
        if req.method == "POST":
            body = json.loads(req.content)
            count = max(1, size // 5_000_000)
            assert body == {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                "chunk_size": min(size, 5_000_000), "total_chunk_count": count}}
            return httpx.Response(200, json={"error": {"code": "ok"}, "data": {
                "publish_id": "draft", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_token=secret-signed"}})
        assert "Authorization" not in req.headers
        offset = 0 if len(calls) == 2 else 5_000_000
        end = offset + len(req.content)
        assert req.headers["Content-Range"] == f"bytes {offset}-{end - 1}/{size}"
        return httpx.Response(201 if end == size else 206)
    assert adapter(TikTok, handler).upload(kit, dry_run=False, confirm=True,
                                           chunk_size=5_000_000)["status"] == "draft_uploaded"
    assert "secret-signed" not in caplog.text
    assert "secret-access" not in caplog.text


def test_tiktok_error_body_and_transfer_failure(kit):
    for body in ({"error": {"code": "access_token_invalid", "message": "secret"}},
                 {"error": {"code": "ok"}, "data": {"publish_id": "x", "upload_url": "https://evil.test/"}}):
        with pytest.raises(PublishError):
            adapter(TikTok, lambda req: httpx.Response(200, json=body)).upload(kit, dry_run=False, confirm=True)


def test_tiktok_transfer_failure_is_not_reinitialized(kit):
    calls = []
    def handler(req):
        calls.append(req)
        if req.method == "POST":
            return httpx.Response(200, json={"error": {"code": "ok"}, "data": {
                "publish_id": "draft", "upload_url": "https://open-upload.tiktokapis.com/video/"}})
        return httpx.Response(403, text="expired secret-url")
    with pytest.raises(PublishError, match="403"):
        adapter(TikTok, handler).upload(kit, dry_run=False, confirm=True)
    assert len(calls) == 2


@pytest.mark.parametrize("range_header", ["nonsense", "bytes=0-999999999"])
def test_youtube_invalid_acknowledgment(kit, range_header):
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/session"})
        return httpx.Response(308, headers={"Range": range_header})
    with pytest.raises(PublishError, match="range"):
        adapter(YouTube, handler).upload(kit, dry_run=False, confirm=True)


def test_missing_encryption_key(monkeypatch):
    monkeypatch.delenv("PUBLISH_TOKEN_KEY", raising=False)
    with pytest.raises(PublishError, match="PUBLISH_TOKEN_KEY"):
        TokenStore()


@pytest.mark.parametrize("url", ["https://www.googleapis.com:secret/", "http://www.googleapis.com/",
                                  "https://www.googleapis.com.evil.test/", "https://secret@www.googleapis.com/"])
def test_untrusted_upload_urls_are_redacted(url):
    from publish.common import upload_url
    with pytest.raises(PublishError) as error:
        upload_url(url, "googleapis.com")
    assert "secret" not in str(error.value)


def test_youtube_no_progress_is_bounded(kit):
    calls = []
    def handler(req):
        calls.append(req)
        return (httpx.Response(200, headers={"Location": "https://www.googleapis.com/session"})
                if req.method == "POST" else httpx.Response(308))
    with pytest.raises(PublishError, match="no progress"):
        adapter(YouTube, handler).upload(kit, dry_run=False, confirm=True)
    assert len(calls) == 5


def test_kit_path_escape(kit, tmp_path):
    metadata = json.loads((kit / "metadata.json").read_text())
    outside = tmp_path / "synthetic.mp4"
    outside.write_bytes(b"outside")
    metadata["video"] = str(outside)
    (kit / "metadata.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="inside"):
        YouTube().upload(kit)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("PUBLISH_TOKEN_KEY", Fernet.generate_key().decode())
    return TokenStore(tmp_path / "tokens")


def test_token_encryption_and_tampering(store, monkeypatch):
    from cryptography.fernet import Fernet
    store.save("youtube", {"access_token": "secret-access", "refresh_token": "secret-refresh"})
    path = store.directory / "youtube.enc"
    assert b"secret" not in path.read_bytes()
    assert store.load("youtube")["access_token"] == "secret-access"
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    monkeypatch.setenv("PUBLISH_TOKEN_KEY", Fernet.generate_key().decode())
    with pytest.raises(PublishError):
        TokenStore(store.directory).load("youtube")
    path.write_bytes(b"tampered")
    with pytest.raises(PublishError):
        store.load("youtube")


@pytest.mark.parametrize("provider", ["youtube", "tiktok"])
def test_oauth_exchange_refresh_and_state(store, provider):
    calls = []
    def handler(req):
        args = parse_qs(req.content.decode())
        calls.append(args)
        assert args["client_secret"] == ["secret-client"]
        assert ("client_id" if provider == "youtube" else "client_key") in args
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600,
                                        **({"refresh_token": "refresh"} if len(calls) == 1 else {})})
    oauth = OAuth(provider, "client", "secret-client", "https://example.test/callback", store,
                  httpx.Client(transport=httpx.MockTransport(handler)))
    args = parse_qs(urlsplit(oauth.authorization_url()).query)
    with pytest.raises(PublishError):
        oauth.exchange("code", "wrong")
    assert calls == []
    args = parse_qs(urlsplit(oauth.authorization_url()).query)
    oauth.exchange("code", args["state"][0])
    with pytest.raises(PublishError):
        oauth.exchange("code", args["state"][0])
    if provider == "youtube":
        assert "code_verifier" in calls[0] and "code_challenge" in args
    tokens = store.load(provider)
    tokens["expires_at"] = 0
    store.save(provider, tokens)
    assert oauth.access_token() == "new-access"
    assert calls[1]["grant_type"] == ["refresh_token"]
    assert store.load(provider)["refresh_token"] == "refresh"


def test_oauth_error_does_not_store_response(store):
    oauth = OAuth("tiktok", "client", "secret", "https://example.test/callback", store,
                  httpx.Client(transport=httpx.MockTransport(lambda req:
                      httpx.Response(200, json={"error": "invalid_grant", "error_description": "secret"}))))
    state = parse_qs(urlsplit(oauth.authorization_url()).query)["state"][0]
    with pytest.raises(PublishError, match="token request failed") as error:
        oauth.exchange("code", state)
    assert "secret" not in str(error.value)
    assert not store.directory.exists()
