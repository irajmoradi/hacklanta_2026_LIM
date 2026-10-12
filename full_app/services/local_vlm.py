"""Local vLLM/Ollama OpenAI-compatible multimodal chat adapter (stdlib HTTP)."""

import base64
import json
import math
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from services.video_understanding import VideoUnderstandingProvider, log_usage, video_duration, with_retries


class OpenAICompatibleVLMProvider(VideoUnderstandingProvider):
    def __init__(self, model, base_url="http://localhost:8000/v1", *, api_key=None,
                 config=None, max_frames=32, transport=None):
        super().__init__(config)
        if max_frames < 1:
            raise ValueError("max_frames must be positive")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_frames = max_frames
        self.transport = transport or self._post

    def _post(self, payload):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = Request(self.base_url + "/chat/completions", data=json.dumps(payload).encode(), headers=headers)
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.load(response)
        except URLError as error:
            if hasattr(error, "code"):
                raise  # HTTP status determines whether to retry.
            raise ConnectionError("Local VLM transport failed") from error

    def _frames(self, path):
        duration = video_duration(path, self.config.timeout_seconds)
        count = min(self.max_frames, max(1, math.ceil(duration * self.config.fps)))
        # Uniformly cover the entire window even when the frame cap reduces FPS.
        for index in range(count):
            timestamp = index * duration / count
            result = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-ss", str(timestamp), "-i", str(path), "-frames:v", "1",
                 "-vf", "scale=640:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                capture_output=True, check=True, timeout=self.config.processing_timeout_seconds,
            )
            if not result.stdout:
                raise ValueError("Could not sample video frame")
            yield timestamp, result.stdout

    def _infer(self, video_path: Path, prompt, schema):
        content = [{"type": "text", "text": prompt + "\nFrames below are ordered; timestamps are seconds relative to this input. No audio is provided."}]
        for timestamp, frame in self._frames(video_path):
            content.extend([
                {"type": "text", "text": f"timestamp_seconds={timestamp:.3f}"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii")}},
            ])
        payload = {
            "model": self.model, "messages": [{"role": "user", "content": content}],
            "temperature": 0.3,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": schema.model_json_schema(),
            }},
        }
        def request():
            started = time.monotonic()
            response = {}
            try:
                response = self.transport(payload)
                return schema.model_validate_json(response["choices"][0]["message"]["content"])
            finally:
                log_usage("local_vlm", self.model, started, response.get("usage", {}), self.config)
        return with_retries(request, self.config, "local_chat")
