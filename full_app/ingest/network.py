"""Private HTTPS transport: pin validated DNS results to the actual socket.

No process-global socket patches, ambient proxies, cookies, or URL credentials.
Every redirect is revalidated. Compression is rejected before decompression.
"""
import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request

from server.security import https_url, public_address
from .models import IngestError

HOSTS = ('youtube.com', 'youtu.be', 'googlevideo.com', 'ytimg.com',
         'youtubei.googleapis.com', 'twitch.tv', 'ttvnw.net', 'jtvnw.net', 'twitchcdn.net')


def validate_target(url):
    parsed = https_url(url)
    if not any(parsed.hostname == h or parsed.hostname.endswith('.' + h) for h in HOSTS):
        raise IngestError('Download host is not allowed')
    return parsed


def public_connection(address, timeout=30, source_address=None):
    host, port = address
    if port != 443:
        raise IngestError('Only HTTPS download connections are supported')
    records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not records or any(not public_address(record[4][0]) for record in records):
        raise IngestError('Download host must resolve only to public addresses')
    # Connect directly to these numeric addresses: never resolve a second time.
    for family, kind, protocol, _, destination in records:
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(timeout)
            if source_address:
                connection.bind(source_address)
            connection.connect(destination)
            return connection
        except OSError:
            connection.close()
    raise IngestError('Could not connect to download host')


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = public_connection


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        validate_target(request.full_url)
        return self.do_open(PublicHTTPSConnection, request, context=ssl.create_default_context())


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        try:
            validate_target(url)
        except ValueError:
            if response is not None:
                response.close()
            raise
        return super().redirect_request(request, response, code, message, headers, url)


class BoundedReader:
    def __init__(self, response, limit, deadline):
        self.response, self.remaining, self.deadline = response, limit, deadline

    def read(self, size=-1):
        if time.monotonic() > self.deadline:
            self.close()
            raise IngestError('URL import timed out')
        read_all = size is None or size < 0
        budget = min(self.remaining, 8 * 1024**2) if read_all else self.remaining
        data = self.response.read(budget + 1 if read_all else min(self.remaining + 1, size))
        self.remaining -= len(data)
        if self.remaining < 0 or read_all and len(data) > budget:
            self.close()
            raise IngestError('Download response exceeds byte limit')
        return data

    def close(self):
        self.response.close()

    @property
    def closed(self):
        return self.response.closed


def open_request(request, *, limit, deadline):
    """Adapt the yt-dlp Request/Response interface without its fallback transports."""
    from yt_dlp.networking import Response
    from yt_dlp.networking.exceptions import HTTPError
    validate_target(request.url)
    if time.monotonic() >= deadline:
        raise IngestError('URL import timed out')
    # Construct an explicit opener: no HTTP, FTP, file, data or ambient proxies.
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.ProxyHandler({}), PublicHTTPSHandler(), SafeRedirect(),
                    urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor(),
                    urllib.request.UnknownHandler()):
        opener.add_handler(handler)
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in {'authorization', 'proxy-authorization', 'cookie', 'host', 'accept-encoding'}}
    headers['Accept-Encoding'] = 'identity'
    incoming = urllib.request.Request(request.url, data=request.data, headers=headers, method=request.method)
    error = False
    try:
        response = opener.open(incoming, timeout=min(30, max(.1, deadline - time.monotonic())))
    except urllib.error.HTTPError as exc:
        response, error = exc, True
    if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
        response.close()
        raise IngestError('Compressed HTTP responses are not accepted')
    adapted = Response(BoundedReader(response, limit, deadline), headers=response.headers,
                       url=response.url, status=response.status, reason=response.reason)
    if error:
        raise HTTPError(adapted)
    return adapted
