"""Gemini provider and backwards-compatible Flask pipeline client."""

from collections import OrderedDict
from services.response_schema import compatible_schema, parse_response
from services.call_budget import CallBudget
from dataclasses import dataclass
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
import threading
import time

from google import genai
from google.genai import types

from models.schemas import ClipList, EditPlan
from services.video_understanding import (
    VideoUnderstandingProvider, log_usage, with_retries,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoSource:
    """Deferred upload handle; keeps long source videos off the network until sliced."""
    path: Path


class GeminiProvider(VideoUnderstandingProvider):
    def __init__(self, api_key=None, model=None, *, config=None, client=None,
                 vertexai=None, media_resolution="low", agentic=False,
                 cache_ttl_seconds=3600, cache_size=32, inline_limit_bytes=20 * 1024 * 1024):
        super().__init__(config)
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        from services.provider_config import gemini_credentials
        key, self.vertexai = gemini_credentials(api_key, vertexai)
        if client is None and not key:
            raise ValueError("Set GOOGLE_API_KEY for Vertex express or GEMINI_API_KEY for AI Studio")
        if media_resolution not in {"low", "medium", "high"}:
            raise ValueError("media_resolution must be low, medium, or high")
        if cache_ttl_seconds <= 0 or cache_size < 1 or inline_limit_bytes < 1:
            raise ValueError("cache and inline limits must be positive")
        self.client = client or genai.Client(
            api_key=key, vertexai=self.vertexai,
            http_options=types.HttpOptions(
                timeout=int(self.config.timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self.media_resolution = "MEDIA_RESOLUTION_" + media_resolution.upper()
        self.agentic = agentic
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_size = cache_size
        self.inline_limit_bytes = inline_limit_bytes
        self._cache = OrderedDict()
        self._cache_lock = threading.RLock()
        self._agentic_warned = False
        self.budget = CallBudget()
        self.parallel_scoring = True

    def upload_video(self, video_path: str | Path) -> VideoSource:
        """Stage a source; find_clips uploads reusable chunks on demand."""
        path = Path(video_path).resolve(strict=True)
        return VideoSource(path)

    def _upload_file(self, path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        key = digest.hexdigest()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached:
                uploaded, deadline = cached
                if time.monotonic() < deadline:
                    try:
                        refreshed = with_retries(lambda: self.client.files.get(name=uploaded.name), self.config, "file_get")
                        if getattr(getattr(refreshed, "state", None), "name", None) == "ACTIVE":
                            self._cache.move_to_end(key)
                            return refreshed
                    except Exception as error:
                        if str(getattr(error, "code", None) or getattr(error, "status_code", None)) != "404":
                            raise
                self.delete_file(uploaded)
                self._cache.pop(key, None)
            started = time.monotonic()
            uploaded = with_retries(lambda: self.client.files.upload(file=str(path)), self.config, "upload")
            try:
                while getattr(getattr(uploaded, "state", None), "name", None) != "ACTIVE":
                    if getattr(getattr(uploaded, "state", None), "name", None) == "FAILED":
                        raise RuntimeError("Gemini failed to process video")
                    if time.monotonic() - started >= self.config.processing_timeout_seconds:
                        raise TimeoutError("Gemini file processing timed out")
                    time.sleep(min(2, self.config.processing_timeout_seconds))
                    uploaded = with_retries(lambda: self.client.files.get(name=uploaded.name), self.config, "file_get")
            except Exception:
                self.delete_file(uploaded)
                raise
            self._cache[key] = (uploaded, time.monotonic() + self.cache_ttl_seconds)
            while len(self._cache) > self.cache_size:
                _, (evicted, _) = self._cache.popitem(last=False)
                self.delete_file(evicted)
            LOG.info("vlm upload elapsed_seconds=%.3f", time.monotonic() - started)
            return uploaded

    def delete_file(self, uploaded_file):
        if isinstance(uploaded_file, VideoSource):
            return  # A staged handle owns no remote file.
        with self._cache_lock:
            for key, (cached, _) in list(self._cache.items()):
                if cached.name == uploaded_file.name:
                    del self._cache[key]
            try:
                with_retries(lambda: self.client.files.delete(name=uploaded_file.name), self.config, "file_delete")
            except Exception as error:
                LOG.warning("vlm file cleanup failed error_type=%s", type(error).__name__)

    def close(self):
        with self._cache_lock:
            for uploaded, _ in list(self._cache.values()):
                self.delete_file(uploaded)
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _video_part(self, path):
        mime = mimetypes.guess_type(str(path))[0] or "video/mp4"
        if self.vertexai:
            # The Developer File API is not available on Vertex express.
            if Path(path).stat().st_size > self.inline_limit_bytes:
                raise ValueError("Vertex inline video exceeds limit; reduce chunk_seconds or transcode the source")
            part = types.Part.from_bytes(data=Path(path).read_bytes(), mime_type=mime)
        else:
            uploaded = self._upload_file(path)
            part = types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type or mime)
        part.video_metadata = types.VideoMetadata(fps=self.config.fps)
        return part

    def _generation_config(self, schema, temperature, video):
        kwargs = dict(response_mime_type="application/json", response_json_schema=compatible_schema(schema.model_json_schema()),
                      temperature=temperature)
        if video:
            kwargs["media_resolution"] = self.media_resolution
        return types.GenerateContentConfig(**kwargs)

    def _generate(self, contents, schema, temperature=0.3, video=False):
        config = self._generation_config(schema, temperature, video)
        def request():
            started = time.monotonic()
            response = None
            try:
                self.budget.reserve()
                response = self.client.models.generate_content(model=self.model, contents=contents, config=config)
                return parse_response(schema, response.text or "")
            finally:
                usage = getattr(response, "usage_metadata", None)
                log_usage("gemini", self.model, started, {
                    "prompt_tokens": getattr(usage, "prompt_token_count", 0),
                    "completion_tokens": (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0),
                }, self.config)
        return with_retries(request, self.config, "generate_content")

    def _infer(self, video_path, prompt, schema):
        if self.agentic:
            interactions = None if self.vertexai else getattr(self.client, "interactions", None)
            if not self.vertexai and callable(getattr(interactions, "create", None)):
                return self._infer_agentic(video_path, prompt, schema)
            if not self._agentic_warned:
                LOG.warning("Agentic video processing is unavailable for this SDK/backend; using standard sampling")
                self._agentic_warned = True
        if self.vertexai and getattr(self, 'auto_proxy', False) and Path(video_path).stat().st_size > self.inline_limit_bytes:
            import tempfile
            import subprocess
            from services.video_understanding import video_duration
            duration = video_duration(video_path)
            bitrate = max(32, int(self.inline_limit_bytes * 8 * .8 / duration / 1000) - 32)
            with tempfile.TemporaryDirectory(prefix='lim-vertex-') as directory:
                proxy = Path(directory) / 'proxy.mp4'
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(video_path),
                    '-vf', "scale=w='min(960,iw)':h=-2", '-r', str(self.config.fps),
                    '-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-b:v', f'{bitrate}k',
                    '-maxrate', f'{bitrate}k', '-bufsize', f'{bitrate*2}k',
                    '-c:a', 'aac', '-b:a', '32k', '-ac', '1', str(proxy)],
                    check=True, capture_output=True, timeout=self.config.processing_timeout_seconds)
                return self._generate([self._video_part(proxy), prompt], schema, video=True)
        return self._generate([self._video_part(video_path), prompt], schema, video=True)

    def _infer_agentic(self, video_path, prompt, schema):
        uploaded = self._upload_file(video_path)
        def request():
            started = time.monotonic()
            response = None
            try:
                self.budget.reserve()
                response = self.client.interactions.create(
                    model=self.model,
                    input=[{"type": "video", "uri": uploaded.uri, "mime_type": uploaded.mime_type,
                            "processing": "agentic", "resolution": self.media_resolution.removeprefix("MEDIA_RESOLUTION_").lower()},
                           {"type": "text", "text": prompt}],
                    response_format={"type": "text", "mime_type": "application/json", "schema": compatible_schema(schema.model_json_schema())},
                    timeout=self.config.timeout_seconds,
                )
                return parse_response(schema, response.output_text or "")
            finally:
                usage = getattr(response, "usage", None)
                log_usage("gemini_agentic", self.model, started, {
                    "prompt_tokens": (getattr(usage, "total_input_tokens", 0) or 0) + (getattr(usage, "total_tool_use_tokens", 0) or 0),
                    "completion_tokens": (getattr(usage, "total_output_tokens", 0) or 0) + (getattr(usage, "total_thought_tokens", 0) or 0),
                }, self.config)
        return with_retries(request, self.config, "agentic_video")

    def find_clips(self, uploaded_file, prompt: str) -> list[dict]:
        if isinstance(uploaded_file, VideoSource):
            result = self.analyze_video(uploaded_file.path, prompt)
        elif isinstance(uploaded_file, (str, Path)):
            result = self.analyze_video(uploaded_file, prompt)
        else:
            # Support callers holding an existing SDK File, too.
            part = types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=uploaded_file.mime_type)
            part.video_metadata = types.VideoMetadata(fps=self.config.fps)
            result = self._generate([part, prompt], ClipList, video=True)
        return [clip.model_dump() for clip in result.clips]

    def detect_game_frames(self, images):
        from pydantic import BaseModel, Field
        from typing import Literal
        class Detection(BaseModel):
            game: Literal['generic', 'valorant', 'overwatch2', 'deadlock', 'league_of_legends']
            confidence: float = Field(ge=0, le=1)
        result = self._generate([*[types.Part.from_bytes(data=image, mime_type='image/png') for image in images[:3]],
            'Identify the game from HUD layout, ability bar and text. Use generic if uncertain.'], Detection)
        return result.game, result.confidence

    def plan_edit(self, prompt: str) -> dict:
        return self._generate([prompt], EditPlan, temperature=0.7).model_dump()

    def generate_thumbnail(self, image_path, prompt, output_path) -> Path:
        output_path = Path(output_path)
        response = with_retries(lambda: (self.budget.reserve(), self.client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=[types.Part.from_bytes(data=Path(image_path).read_bytes(), mime_type="image/jpeg"), prompt],
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        ))[1], self.config, "thumbnail")
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data:
                    output_path.write_bytes(part.inline_data.data)
                    return output_path
        raise RuntimeError("Gemini did not return an image")


class GeminiVideoClient(GeminiProvider):
    """Legacy name retained for app.py's upload/find/plan/thumbnail sequence."""
