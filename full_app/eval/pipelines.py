"""Lazy integrations. Paid Gemini use requires explicit live-smoke opt-in."""

import importlib
import os
from pathlib import Path
import threading
from types import SimpleNamespace


class Unavailable(RuntimeError):
    """A pipeline cannot run in this checkout/configuration."""


def optional_function(module, name):
    try:
        loaded = importlib.import_module(module)
    except ImportError as exc:
        raise Unavailable(f"Optional import unavailable: {module} ({exc})") from exc
    function = getattr(loaded, name, None)
    if not callable(function):
        raise Unavailable(f"Optional hook unavailable: {module}.{name}")
    return function


def signals_only(video):
    candidates = optional_function("signals", "detect_candidates")(str(video["path"]))
    return {"clips": candidates, "cost_usd": 0.0}


def signals_vlm(video, scorer=None):
    # A scorer must be a local/mock adapter; remote paid scoring is not enabled here.
    if scorer is None:
        raise Unavailable("No local window scorer configured; use --window-scorer or --replay")
    candidates = optional_function("signals", "detect_candidates")(str(video["path"]))
    return scorer(str(video["path"]), candidates)


class GenerationBudget:
    """Count SDK generation attempts, including failed calls, across all videos."""
    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def invoke(self, function, **kwargs):
        with self.lock:
            if self.calls >= 3:
                raise Unavailable("Live smoke budget exhausted (maximum 3 generation calls)")
            self.calls += 1
        return function(**kwargs)


class GeminiOnly:
    def __init__(self, live_smoke=False, client=None):
        # client is an offline fake SDK, not a high-level provider that could
        # hide additional inference calls. Real clients are constructed below.
        self.live_smoke = live_smoke
        self.client = client
        self.budget = GenerationBudget()

    @property
    def calls(self):
        return self.budget.calls

    def __call__(self, video):
        if self.client is None and not self.live_smoke:
            raise Unavailable("Paid provider disabled; use replay or explicit --live-smoke")
        if self.calls >= 3:
            raise Unavailable("Live smoke budget exhausted (maximum 3 generation calls)")
        from services.video_understanding import ProviderConfig, video_duration
        from services.gemini_client import GeminiVideoClient
        from google import genai
        from google.genai import types

        # Probe actual media, not author-supplied manifest duration. One bounded
        # input chunk per smoke video; reject before creating/uploading a client.
        duration = video_duration(video["path"])
        if duration > 600:
            raise Unavailable("Live smoke requires a single chunk (source duration <=600 seconds)")
        vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
        key = os.getenv("GOOGLE_API_KEY" if vertex else "GEMINI_API_KEY")
        if self.client is None and not key:
            raise Unavailable("Set GOOGLE_API_KEY with GOOGLE_GENAI_USE_VERTEXAI=true, or GEMINI_API_KEY")
        sdk = self.client if self.client is not None else genai.Client(
            api_key=key, vertexai=vertex,
            http_options=types.HttpOptions(timeout=120000,
                retry_options=types.HttpRetryOptions(attempts=1)))
        guarded = SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **kwargs:
                self.budget.invoke(sdk.models.generate_content, **kwargs)),
            files=sdk.files, close=sdk.close)
        provider = None
        try:
            provider = GeminiVideoClient(client=guarded, vertexai=vertex, agentic=False,
                config=ProviderConfig(attempts=1, chunk_seconds=600, overlap_seconds=0),
                model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"))
            def timestamp(seconds):
                return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
            template = (Path(__file__).resolve().parents[1] / "prompts" / "clip_finder.txt").read_text(encoding="utf-8")
            prompt = template.format(duration=duration, duration_mmss=timestamp(duration),
                                     one_third_mmss=timestamp(duration / 3),
                                     two_third_mmss=timestamp(duration * 2 / 3), user_prompt="")
            uploaded = provider.upload_video(str(video["path"]))
            return {"clips": provider.find_clips(uploaded, prompt), "cost_usd": None}
        finally:
            # find_clips retains cached remote files; close owns their deletion.
            if provider is not None:
                provider.close()
            else:
                sdk.close()


def local_window_scorer(video_path, candidates):
    """Real local VLM adapter; no Gemini fallback and no paid provider requests."""
    from services.local_vlm import OpenAICompatibleVLMProvider
    from pipeline.ranking import candidate_dict
    from urllib.parse import urlparse
    model = os.getenv("LOCAL_VLM_MODEL")
    base_url = os.getenv("LOCAL_VLM_BASE_URL", "http://localhost:8000/v1")
    if not model:
        raise Unavailable("Local scorer requires LOCAL_VLM_MODEL and a running local server")
    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise Unavailable("Evaluation local scorer requires a loopback endpoint")
    provider = OpenAICompatibleVLMProvider(model=model, base_url=base_url)
    try:
        normalized = [candidate_dict(c) for c in candidates]
        scored = provider.score_windows(video_path, normalized)
        return {"clips": [dict(start=c.start, end=c.end, score=c.hype / 10)
                          for c in scored if c.player_alive is True and c.kind != "neutral"],
                "cost_usd": 0.0}
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def mock_pipeline(name):
    """Fixed predictions for CI fixtures, never read the ground-truth labels."""
    def predict(video):
        clips = []
        if video["id"] == "bursts":
            clips = [{"start": 1, "end": 2, "score": 0.9}]
            if name != "signals-only":
                clips.append({"start": 4, "end": 5, "score": 0.8})
        return {"clips": clips, "cost_usd": 0.0}
    return predict
