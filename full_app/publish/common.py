"""Small HTTP boundary: never expose provider bodies, tokens or signed URLs."""
from urllib.parse import urlsplit
from contextvars import ContextVar
import logging

import httpx


_private_request = ContextVar("publish_private_request", default=False)


class _PrivateHTTP(logging.Filter):
    def filter(self, record):
        return not _private_request.get()


# httpx logs signed URLs at INFO; httpcore wire debugging can include headers.
# Suppress these records only within this module's requests in the current context.
for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
              "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_PrivateHTTP())


class PublishError(RuntimeError):
    pass


def request(client, method, url, **kwargs):
    marker = _private_request.set(True)
    try:
        return client.request(method, url, timeout=60, follow_redirects=False, **kwargs)
    except httpx.HTTPError:
        raise PublishError("Provider transport failed; upload outcome may be unknown") from None
    finally:
        _private_request.reset(marker)


def expect(response, statuses):
    if response.status_code not in statuses:
        raise PublishError(f"Provider returned HTTP {response.status_code}")
    return response


def json_body(response):
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except ValueError:
        raise PublishError("Invalid provider response") from None


def upload_url(value, domain):
    if not isinstance(value, str):
        raise PublishError("Missing upload URL")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443) or not parsed.hostname
            or not (parsed.hostname == domain or parsed.hostname.endswith("." + domain))):
        raise PublishError("Untrusted upload URL")
    return value
