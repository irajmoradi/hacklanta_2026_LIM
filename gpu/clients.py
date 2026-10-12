"""Explicit adapters for audio_ai.backends and vjepa's encoder protocol.

Keep the repository root and full_app on PYTHONPATH when using app model types.
SAM's existing RemoteSegmenter already speaks the /segment contract.
"""
import base64
import json
import math
import os
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import numpy as np

from gpu.schemas import MAX_BODY, MAX_RESPONSE, MODEL_ID, REQUESTS, decode, validate_response


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Transport:
    def __init__(self, url, token=None, timeout=290):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Expected an HTTPS endpoint without credentials/query/fragment")
        self.url = url
        self.token = token if token is not None else os.environ.get("GPU_API_TOKEN", "")
        if not self.token or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("Token and bounded timeout required")
        self.timeout = timeout

    def call(self, kind, values):
        request = REQUESTS[kind].model_validate(values)
        media = decode(kind, request)
        body = json.dumps(values).encode()
        if len(body) > MAX_BODY:
            raise ValueError("Request too large")
        try:
            req = Request(self.url, data=body, method="POST", headers={
                "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
            with build_opener(NoRedirect).open(req, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("Response too large")
            return validate_response(kind, json.loads(raw), request, media)
        except Exception:
            raise RuntimeError("Remote GPU request failed") from None


def transcribe(samples, model="large-v3", allow_downloads=False):
    """Same call signature/Word return type as audio_ai.backends.transcribe.

    Explicit invocation opts into remote inference; model/allow_downloads are
    compatibility arguments. Server model is always large-v3. No automatic retry.
    """
    from audio_ai.models import Word
    audio = np.asarray(samples, dtype="<f4")
    if audio.ndim != 1 or not np.isfinite(audio).all() or np.any(np.abs(audio) > 1):
        raise ValueError("Expected normalized mono samples at 16 kHz")
    if not len(audio):
        return []
    transport = Transport(os.environ["WHISPER_ENDPOINT_URL"])
    words = []
    for offset in range(0, len(audio), 60 * 16000):
        chunk = audio[offset:offset + 60 * 16000]
        result = transport.call("transcribe", {"pcm_f32le": base64.b64encode(chunk.tobytes()).decode()})
        words.extend(Word(**{**word, "start": word["start"] + offset/16000,
                            "end": word["end"] + offset/16000}) for word in result["words"])
    return words


class RemoteEncoder:
    """Pass to vjepa.features.extract(..., encoder=...) or vjepa.score()."""
    def __init__(self, revision=None):
        revision = revision or os.environ["VJEPA_REVISION"]
        import re
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Expected a pinned V-JEPA revision")
        self.identity = f"hf-mean-v1:{MODEL_ID}@{revision}"
        self.transport = Transport(os.environ["VJEPA_ENDPOINT_URL"])

    def encode(self, videos):
        vectors = []
        for video in videos:
            video = np.asarray(video)
            if video.dtype != np.uint8 or video.ndim != 4 or video.shape[1:] != (256, 256, 3):
                raise ValueError("Expected uint8 [frames,256,256,3]")
            result = self.transport.call("embed", {
                "frames": len(video), "encoder": self.identity,
                "rgb_u8": base64.b64encode(video.tobytes()).decode()})
            vectors.append(result["features"])
        return np.asarray(vectors, dtype=np.float32).reshape(-1, 1024)
