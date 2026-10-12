"""discord.py adapter. Loaded only when the optional bot is started."""
from typing import Literal, Optional

import discord
from discord import app_commands

from .api import JobAPI
from .core import BotError, MontageService, Options, select_source


class ChannelSink:
    def __init__(self, channel, reference=None):
        self.channel = channel
        self.send_options = {"allowed_mentions": discord.AllowedMentions.none()}
        if reference is not None:
            self.send_options["reference"] = reference

    async def send_status(self, text):
        return await self.channel.send(text, **self.send_options)

    async def deliver(self, text, path, link):
        text = discord.utils.escape_markdown(text)
        if path is None:
            await self.channel.send(f"{text}\nDownload: {link}", **self.send_options)
            return
        try:
            video = discord.File(path, filename="montage.mp4")
            try:
                await self.channel.send(text, file=video, **self.send_options)
            finally:
                video.close()
        except discord.HTTPException as exc:
            if exc.status != 413 and exc.code != 40005:
                raise
            await self.channel.send(f"{text}\nDownload: {link}", **self.send_options)


class MontageClient(discord.Client):
    def __init__(self, config, api=None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.api = api or JobAPI(config)
        self.service = MontageService(config, self.api)
        self.tree = app_commands.CommandTree(self)

        @self.tree.command(name="montage", description="Make a montage from your own gameplay video or direct VOD link")
        @app_commands.guild_only()
        @app_commands.describe(video="Your gameplay video", url="Direct HTTPS video URL on an allowed host",
                               length="Maximum planned duration in seconds", game="Game name (optional context)")
        async def montage(interaction: discord.Interaction, video: Optional[discord.Attachment] = None,
                          url: Optional[str] = None, mode: Literal["nice", "mean"] = "nice",
                          preset: Literal["landscape", "vertical"] = "landscape",
                          game: str = "", length: app_commands.Range[int, 1, 3600] = 60):
            await self.handle_command(interaction, video, url, mode, preset, game, length)

    async def setup_hook(self):
        await self.api.open()
        await self.tree.sync()

    async def close(self):
        await self.api.close()
        await super().close()

    async def handle_command(self, interaction, video=None, url=None, mode="nice", preset="landscape", game="", length=60):
        try:
            if interaction.channel_id not in self.config.channels or interaction.guild is None:
                raise BotError("Montages are disabled in this channel.")
            options = Options(mode, preset, game, length)
            options.validate()
            source = select_source(self.config, video, url)
        except BotError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        # Use regular channel messages for progress/results: jobs may outlast the
        # interaction webhook lifetime. Acknowledge before any network transfer.
        await interaction.response.send_message("Accepted. Montage progress will appear in this channel.", ephemeral=True)
        await self.service.run(interaction.user.id, interaction.channel_id, source, options,
                               ChannelSink(interaction.channel), interaction.guild.filesize_limit)

    async def on_message(self, message):
        if message.author.bot or message.guild is None or message.channel.id not in self.config.channels:
            return
        attachments = [a for a in message.attachments if a.filename.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi"))]
        # An entire message containing a URL is an explicit submission; ordinary
        # conversation and incidental links are ignored.
        url = message.content.strip().strip("<>")
        url = url if url.startswith("https://") and not any(c.isspace() for c in url) else None
        if not attachments and not url:
            return
        sink = ChannelSink(message.channel, reference=message)
        try:
            if len(attachments) > 1:
                raise BotError("Submit one video at a time.")
            source = select_source(self.config, attachments[0] if attachments else None, url)
            await self.service.run(message.author.id, message.channel.id, source, Options(), sink, message.guild.filesize_limit)
        except BotError as exc:
            await sink.send_status(str(exc))
