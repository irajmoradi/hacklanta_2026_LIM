"""Discord-independent request validation and montage orchestration."""
import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlsplit
from server.security import safe_component, safe_path


class BotError(Exception):
    """A safe, user-facing error (never include remote response bodies)."""


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    channels: frozenset[int]
    api_url: str = "http://127.0.0.1:8000"
    public_url: str = "http://127.0.0.1:8000"
    vod_hosts: frozenset[str] = frozenset()
    max_input: int = 100 * 1024 * 1024
    max_upload: int = 10 * 1024 * 1024
    cooldown: int = 300
    poll_seconds: float = 3
    timeout: int = 1800
    max_active: int = 4

    @classmethod
    def from_env(cls):
        try:
            api = os.getenv("DISCORD_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
            config = cls(
                token=os.environ["DISCORD_BOT_TOKEN"],
                channels=frozenset(int(x.strip()) for x in os.environ["DISCORD_ALLOWED_CHANNEL_IDS"].split(",") if x.strip()),
                api_url=api,
                public_url=os.getenv("DISCORD_PUBLIC_BASE_URL", api).rstrip("/"),
                vod_hosts=frozenset(x.strip().lower() for x in os.getenv("DISCORD_VOD_HOSTS", "").split(",") if x.strip()),
                max_input=int(os.getenv("DISCORD_MAX_INPUT_BYTES", str(100 * 1024 * 1024))),
                max_upload=int(os.getenv("DISCORD_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
                cooldown=int(os.getenv("DISCORD_USER_COOLDOWN_SECONDS", "300")),
                poll_seconds=float(os.getenv("DISCORD_POLL_SECONDS", "3")),
                timeout=int(os.getenv("DISCORD_JOB_TIMEOUT_SECONDS", "1800")),
                max_active=int(os.getenv("DISCORD_MAX_ACTIVE_JOBS", "4")),
            )
            if not config.token or not config.channels or any(x <= 0 for x in config.channels):
                raise ValueError()
            if not all(0 < x < float("inf") for x in (config.max_input, config.max_upload, config.cooldown, config.poll_seconds, config.timeout, config.max_active)):
                raise ValueError()
            for url in (config.api_url, config.public_url):
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError()
            return config
        except (KeyError, ValueError):
            raise BotError("Invalid bot configuration; check the documented environment variables.") from None


@dataclass(frozen=True)
class Options:
    mode: str = "nice"
    preset: str = "landscape"
    game: str = ""
    length: int = 60

    def validate(self):
        if self.mode not in {"nice", "mean"} or self.preset not in {"landscape", "vertical"}:
            raise BotError("Choose mode nice/mean and preset landscape/vertical.")
        if type(self.length) is not int or not 1 <= self.length <= 3600:
            raise BotError("Length must be 1–3600 seconds.")
        if len(self.game) > 100 or any(ord(c) < 32 for c in self.game):
            raise BotError("Game must be at most 100 characters, on one line.")

    def analysis(self):
        return {"mode": self.mode, "max_duration": self.length,
                "prompt": f"Gameplay context: {self.game}" if self.game else ""}


@dataclass(frozen=True)
class Source:
    url: str
    filename: str
    size: int | None = None


def select_source(config, attachment=None, url=None):
    if (attachment is None) == (not url):
        raise BotError("Provide exactly one video attachment or direct VOD URL.")
    if attachment is not None:
        # Never use a remote filename as a filesystem path (including Windows paths).
        filename = PureWindowsPath(attachment.filename).name
        try:
            safe_component(filename)
        except ValueError:
            filename = 'source' + Path(filename).suffix.lower()
        if Path(filename).suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
            raise BotError("Attach an MP4, MOV, MKV, WebM, or AVI video.")
        if not 0 < attachment.size <= config.max_input:
            raise BotError("Video exceeds the configured input size limit or is empty.")
        url = attachment.url
        hosts = {"cdn.discordapp.com", "media.discordapp.net"}
    else:
        filename = "vod.mp4"
        hosts = config.vod_hosts
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in hosts and
                 not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise BotError("Use an HTTPS video URL on an allowed host; ask the operator to configure DISCORD_VOD_HOSTS.")
    return Source(url, filename, attachment.size if attachment else None)


def share_title(snapshot, options):
    kit = snapshot.get("share_kit")
    title = kit.get("title") if isinstance(kit, dict) else None
    if not isinstance(title, str) or not title.strip():
        title = f"{options.game or 'Gameplay'} — {'Highlights' if options.mode == 'nice' else 'Funny fails'}"
    return " ".join(title.split())[:180]


class MontageService:
    def __init__(self, config, api, clock=time.monotonic):
        self.config, self.api, self.clock = config, api, clock
        self.active = set()
        self.last = {}

    async def run(self, user_id, channel_id, source, options, sink, upload_limit=None):
        """sink provides send_status(), status.edit(), and deliver(text, path)."""
        if channel_id not in self.config.channels:
            await sink.send_status("Montages are disabled in this channel.")
            return
        options.validate()
        now = self.clock()
        self.last = {user: stamp for user, stamp in self.last.items() if now - stamp < self.config.cooldown}
        if user_id in self.active or user_id in self.last:
            await sink.send_status("You already have a montage running or are on cooldown. Try again later.")
            return
        if len(self.active) >= self.config.max_active or len(self.last) >= 4096:
            await sink.send_status('The montage service is busy. Try again later.')
            return
        self.active.add(user_id)
        self.last[user_id] = now
        job_id = None
        status = None
        async def workflow():
            nonlocal job_id, status
            status = await sink.send_status("Downloading video…")
            with TemporaryDirectory(prefix="lim-discord-") as temp:
                source_path = safe_path(temp, source.filename)
                await self.api.fetch_source(source.url, source_path, self.config.max_input)
                await status.edit(content="Uploading video to the montage service…")
                snapshot = await self.api.upload(source_path)
                job_id = safe_component(snapshot.get("id") or snapshot["job_id"])
                await self.api.action(job_id, "analyze", options.analysis())
                await self.wait_for(job_id, {"planned"}, status)
                await self.api.action(job_id, "render", {"preset": options.preset, "generate_thumbnails": False})
                snapshot = await self.wait_for(job_id, {"done"}, status)
                limit = min(self.config.max_upload, upload_limit or self.config.max_upload)
                output = Path(temp) / "montage.mp4"
                fits = await self.api.download(job_id, output, limit)
                title = share_title(snapshot, options)
                link = f"{self.config.public_url}/api/jobs/{quote(job_id, safe='')}/download"
                await sink.deliver(f"Share-kit title: {title}", output if fits else None, link)
                await status.edit(content="Montage ready!")
        try:
            await asyncio.wait_for(workflow(), timeout=self.config.timeout)
        except (Exception, asyncio.CancelledError) as exc:
            if job_id:
                try:
                    await asyncio.wait_for(self.api.action(job_id, "cancel", {}), timeout=10)
                except Exception:
                    pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            message = str(exc) if isinstance(exc, BotError) else "Montage failed or timed out. Please try again after the cooldown."
            if status:
                await status.edit(content=message)
            else:
                await sink.send_status(message)
        finally:
            self.active.discard(user_id)

    async def wait_for(self, job_id, targets, status):
        previous = None
        while True:
            snapshot = await self.api.snapshot(job_id)
            state = snapshot.get("status", "queued")
            if state in {"error", "cancelled"}:
                raise BotError("The montage service failed or cancelled this job. Please contact the operator.")
            progress = snapshot.get("progress", 0)
            percent = round(max(0, min(1, progress)) * 100) if isinstance(progress, (int, float)) else 0
            text = f"Montage: {state} ({percent}%)"
            if text != previous:
                await status.edit(content=text)
                previous = text
            if state in targets:
                return snapshot
            await asyncio.sleep(self.config.poll_seconds)
