"""Bounded HTTP transfers; untrusted media uses public-address-only DNS."""
import ipaddress
import socket
from urllib.parse import quote

import aiohttp

from .core import BotError


class PublicResolver(aiohttp.resolver.DefaultResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await super().resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(r["host"]).is_global for r in records):
            raise BotError("Video hosts must resolve only to public Internet addresses.")
        return records


class JobAPI:
    def __init__(self, config):
        self.config = config
        self.session = None
        self.media = None

    async def open(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        self.media = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=PublicResolver()),
            timeout=aiohttp.ClientTimeout(total=300),
        )

    async def close(self):
        for session in (self.session, self.media):
            if session:
                await session.close()

    def url(self, job_id="", action=""):
        return self.config.api_url + "/api/jobs" + ("/" + quote(job_id, safe="") if job_id else "") + ("/" + action if action else "")

    @staticmethod
    def check(response):
        if not 200 <= response.status < 300:
            raise BotError(f"The video/API request failed (HTTP {response.status}).")

    async def upload(self, path):
        with path.open("rb") as video:
            form = aiohttp.FormData()
            form.add_field("video", video, filename=path.name, content_type="application/octet-stream")
            async with self.session.post(self.url(), data=form, allow_redirects=False) as response:
                self.check(response)
                return await response.json()

    async def action(self, job_id, action, payload):
        async with self.session.post(self.url(job_id, action), json=payload, allow_redirects=False) as response:
            self.check(response)
            return await response.json()

    async def snapshot(self, job_id):
        async with self.session.get(self.url(job_id), allow_redirects=False) as response:
            self.check(response)
            return await response.json()

    async def transfer(self, session, url, path, limit):
        # Never follow redirects from user-controlled URLs or the configured API.
        # Count decompressed bytes as well as checking Content-Length.
        async with session.get(url, allow_redirects=False) as response:
            self.check(response)
            if response.content_length is not None and response.content_length > limit:
                return False
            size = 0
            with path.open("wb") as output:
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > limit:
                        return False
                    output.write(chunk)
            if size == 0:
                raise BotError("The video download was empty.")
            return True

    async def fetch_source(self, url, path, limit):
        # aiohttp bypasses resolvers for literal IP addresses, so reject those here.
        from urllib.parse import urlsplit
        host = urlsplit(url).hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise BotError("Use a named public video host, not an IP address.")
        if not await self.transfer(self.media, url, path, limit):
            raise BotError("Video exceeds the configured input size limit.")

    async def download(self, job_id, path, limit):
        return await self.transfer(self.session, self.url(job_id, "download"), path, limit)
