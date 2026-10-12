"""Lazy integrations. Paid Gemini use requires explicit live-smoke opt-in."""

import importlib
import os
from pathlib import Path


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
    scorer = scorer or optional_function("services.eval_adapter", "score_windows")
    candidates = optional_function("signals", "detect_candidates")(str(video["path"]))
    return scorer(str(video["path"]), candidates)


class GeminiOnly:
    def __init__(self, live_smoke=False, client=None):
        self.live_smoke = live_smoke
        self.client = client
        self.calls = 0

    def __call__(self, video):
        if self.client is None:
            if not self.live_smoke:
                raise Unavailable("Paid provider disabled; use replay or explicit --live-smoke")
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise Unavailable("Legacy Gemini adapter requires GEMINI_API_KEY (AI Studio)")
            factory = optional_function("services.gemini_client", "GeminiVideoClient")
            self.client = factory(api_key=key, model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"))
        if self.calls >= 3:
            raise Unavailable("Live smoke budget exhausted (maximum 3 generation calls)")
        duration = video["duration_seconds"]
        def timestamp(seconds):
            return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
        template = (Path(__file__).resolve().parents[1] / "prompts" / "clip_finder.txt").read_text(encoding="utf-8")
        prompt = template.format(duration=duration, duration_mmss=timestamp(duration),
                                 one_third_mmss=timestamp(duration / 3),
                                 two_third_mmss=timestamp(duration * 2 / 3), user_prompt="")
        self.calls += 1
        uploaded = self.client.upload_video(str(video["path"]))
        # Existing find_clips owns uploaded-file cleanup, including on failure.
        return {"clips": self.client.find_clips(uploaded, prompt), "cost_usd": None}


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
