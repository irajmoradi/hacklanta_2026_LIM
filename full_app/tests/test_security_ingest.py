import io
import json
import socket
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import Mock
import urllib.request

import pytest

from ingest import IngestError, prepare
from ingest import media
from ingest.network import BoundedReader, SafeRedirect, public_connection, validate_target


@pytest.mark.parametrize('payload', [b'#EXTM3U\nhttp://127.0.0.1/secret', b'PK\x03\x04archive',
                                      b'GIF89a', b'not video'])
def test_sniff_precedes_probe(tmp_path, monkeypatch, payload):
    path = tmp_path / 'fake.mp4'
    path.write_bytes(payload)
    run = Mock()
    monkeypatch.setattr(media, 'run', run)
    with pytest.raises(IngestError, match='signature'):
        media.probe(path)
    run.assert_not_called()


def test_probe_timeout_and_no_stderr_secrets(tmp_path, monkeypatch):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'\x00\x00\x00\x18ftypisom')
    runner = Mock(side_effect=subprocess.TimeoutExpired('ffprobe', 30))
    monkeypatch.setattr(media.subprocess, 'run', runner)
    with pytest.raises(IngestError, match='timed out'):
        media.probe(path)
    assert runner.call_args.kwargs['timeout'] == 30
    args = runner.call_args.args[0]
    assert args[args.index('-protocol_whitelist') + 1] == 'file'
    runner.side_effect = subprocess.CalledProcessError(1, 'ffprobe', stderr='SECRET_TOKEN')
    with pytest.raises(IngestError) as error:
        media.probe(path)
    assert 'SECRET_TOKEN' not in str(error.value)
    assert error.value.__suppress_context__


def test_synthetic_video_accepted_and_cache_staging_cleaned(video, tmp_path, monkeypatch):
    assert media.probe(video)['width'] == 160
    monkeypatch.setattr(media, 'encode', Mock(side_effect=IngestError('failed')))
    cache = tmp_path / 'cache'
    with pytest.raises(IngestError):
        prepare(video, cache_dir=cache)
    assert not list(cache.rglob('video.mp4'))
    assert not list(cache.rglob('normalize-*'))


def record(address):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))


@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['8.8.8.8', '10.0.0.1'], []])
def test_dns_blocks_all_mixed_or_private_results(monkeypatch, addresses):
    monkeypatch.setattr(socket, 'getaddrinfo', Mock(return_value=[record(a) for a in addresses]))
    create = Mock()
    monkeypatch.setattr(socket, 'socket', create)
    with pytest.raises(IngestError, match='public'):
        public_connection(('youtu.be', 443))
    create.assert_not_called()


def test_dns_pins_checked_address_without_second_lookup(monkeypatch):
    lookup = Mock(side_effect=[[record('8.8.8.8')], [record('127.0.0.1')]])
    monkeypatch.setattr(socket, 'getaddrinfo', lookup)
    connection = Mock()
    monkeypatch.setattr(socket, 'socket', Mock(return_value=connection))
    assert public_connection(('youtu.be', 443)) is connection
    connection.connect.assert_called_once_with(('8.8.8.8', 443))
    assert lookup.call_count == 1


@pytest.mark.parametrize('url', ['https://127.0.0.1/a', 'http://youtube.com/a',
                                  'file:///etc/passwd', 'https://googlevideo.com.evil/a'])
def test_redirects_and_manifest_destinations_rejected(url):
    with pytest.raises(ValueError):
        validate_target(url)
    with pytest.raises(ValueError):
        SafeRedirect().redirect_request(urllib.request.Request('https://youtu.be/a'),
                                        None, 302, '', {}, url)


def test_response_budgets_and_deadline():
    stream = io.BytesIO(b'12345')
    bounded = BoundedReader(stream, 4, time.monotonic() + 10)
    assert bounded.read(2) == b'12'
    with pytest.raises(IngestError, match='byte limit'):
        bounded.read()
    assert stream.closed
    expired = io.BytesIO(b'a')
    with pytest.raises(IngestError, match='timed out'):
        BoundedReader(expired, 2, 0).read()
    assert expired.closed


def test_rejected_redirect_closes_response():
    response = Mock()
    with pytest.raises(ValueError):
        SafeRedirect().redirect_request(urllib.request.Request('https://youtu.be/a'),
                                        response, 302, '', {}, 'https://127.0.0.1/a')
    response.close.assert_called_once()


def test_ytdlp_transport_adapts_real_request(monkeypatch):
    networking = pytest.importorskip('yt_dlp.networking')
    from ingest.network import open_request
    from email.message import Message
    headers = Message()
    headers['Content-Type'] = 'application/octet-stream'
    response = io.BytesIO(b'video')
    response.headers, response.url, response.status, response.reason = headers, 'https://youtu.be/a', 200, 'OK'
    opener = Mock(return_value=response)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', opener)
    request = networking.Request('https://youtu.be/a', headers={'Authorization': 'secret', 'Cookie': 'secret'})
    result = open_request(request, limit=10, deadline=time.monotonic() + 10)
    assert result.read() == b'video'
    result.close()
    sent = opener.call_args.args[0]
    assert not sent.has_header('Authorization') and not sent.has_header('Cookie')
    assert sent.get_header('Accept-encoding') == 'identity'


def test_compressed_http_response_rejected_before_read(monkeypatch):
    networking = pytest.importorskip('yt_dlp.networking')
    from ingest.network import open_request
    response = Mock(headers={'Content-Encoding': 'gzip'})
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', Mock(return_value=response))
    with pytest.raises(IngestError, match='Compressed'):
        open_request(networking.Request('https://youtu.be/a'), limit=100, deadline=time.monotonic() + 10)
    response.read.assert_not_called()
    response.close.assert_called_once()


def test_downloader_manifest_rejection_and_direct_cleanup(tmp_path, monkeypatch):
    import sys
    from ingest.urls import download
    from ingest import Limits
    class YoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            from pathlib import Path
            Path(self.options['outtmpl'].replace('%(ext)s', 'part')).write_bytes(b'partial')
            return {'duration': 2, 'protocol': 'm3u8_native', 'url': 'https://youtube.com/a.m3u8'}
        def process_ie_result(self, *args, **kwargs):
            raise AssertionError('Manifest must not reach a downloader')
    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=YoutubeDL))
    with pytest.raises(IngestError, match='progressive HTTPS'):
        download('https://youtu.be/a', tmp_path, limits=Limits(), owns_content=True)
    assert not list(tmp_path.iterdir())
