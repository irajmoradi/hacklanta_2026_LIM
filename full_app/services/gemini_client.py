"""Gemini provider and backwards-compatible Flask pipeline client."""

from collections import OrderedDict
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
    ProviderConfig, VideoUnderstandingProvider, log_usage, video_duration, with_retries,
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
        self.vertexai = (os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
                         if vertexai is None else vertexai)
        key = api_key or os.getenv("GOOGLE_API_KEY" if self.vertexai else "GEMINI_API_KEY")
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
        kwargs = dict(response_mime_type="application/json", response_schema=schema,
                      temperature=temperature)
        if video:
            kwargs["media_resolution"] = self.media_resolution
            # Only send an agentic flag when the installed SDK explicitly models it.
            fields = types.GenerateContentConfig.model_fields
            if self.agentic and "video_processing_mode" in fields:
                kwargs["video_processing_mode"] = "AGENTIC"
            elif self.agentic and not self._agentic_warned:
                LOG.warning("Agentic video processing is unavailable in this SDK generate_content surface; using standard sampling")
                self._agentic_warned = True
        return types.GenerateContentConfig(**kwargs)

    def _generate(self, contents, schema, temperature=0.3, video=False):
        config = self._generation_config(schema, temperature, video)
        def request():
            started = time.monotonic()
            response = None
            try:
                response = self.client.models.generate_content(model=self.model, contents=contents, config=config)
                return schema.model_validate_json(response.text or "")
            finally:
                usage = getattr(response, "usage_metadata", None)
                log_usage("gemini", self.model, started, {
                    "prompt_tokens": getattr(usage, "prompt_token_count", 0),
                    "completion_tokens": getattr(usage, "candidates_token_count", 0),
                }, self.config)
        return with_retries(request, self.config, "generate_content")

    def _infer(self, video_path, prompt, schema):
        return self._generate([self._video_part(video_path), prompt], schema, video=True)

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

    def plan_edit(self, prompt: str) -> dict:
        return self._generate([prompt], EditPlan, temperature=0.7).model_dump()

    def generate_thumbnail(self, image_path, prompt, output_path) -> Path:
        output_path = Path(output_path)
        response = with_retries(lambda: self.client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=[types.Part.from_bytes(data=Path(image_path).read_bytes(), mime_type="image/jpeg"), prompt],
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        ), self.config, "thumbnail")
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data:
                    output_path.write_bytes(part.inline_data.data)
                    return output_path
        raise RuntimeError("Gemini did not return an image")


class GeminiVideoClient(GeminiProvider):
    """Legacy name retained for app.py's upload/find/plan/thumbnail sequence."""
