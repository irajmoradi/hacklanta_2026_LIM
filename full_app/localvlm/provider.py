"""Gameplay-tuned extension of the EXT-02 provider contract."""

import base64
import math
from pathlib import Path
import time

from models.schemas import ScoringCandidate, ScoredWindow, WindowAssessment
from services.local_vlm import OpenAICompatibleVLMProvider
from services.video_understanding import WINDOW_PROMPT, log_usage, video_duration, video_slice, with_retries
from .prompts import messages, parse_json
from .runtime import RuntimeConfig
from .sampling import SamplerConfig, sample_frames


class LocalVLMProvider(OpenAICompatibleVLMProvider):
    def __init__(self, runtime=None, *, sampler=None, config=None, api_key=None, transport=None):
        self.runtime = runtime or RuntimeConfig()
        self.sampler = sampler or SamplerConfig()
        if self.sampler.image_budget > self.runtime.image_budget:
            raise ValueError("sampler exceeds server image budget")
        super().__init__(self.runtime.model, self.runtime.base_url, api_key=api_key,
                         config=config, transport=transport, max_frames=self.sampler.frames)

    def _infer(self, video_path, prompt, schema, *, peak=None):
        duration = video_duration(video_path, self.config.processing_timeout_seconds)
        turns = messages(prompt, schema)
        content = turns[-1]["content"]
        for sample in sample_frames(video_path, duration, peak, self.sampler, self.config.processing_timeout_seconds):
            content.extend([
                {"type": "text", "text": f"timestamp_seconds={sample.timestamp:.3f} view={sample.label}"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(sample.jpeg).decode("ascii")}},
            ])
        payload = {"model": self.model, "messages": turns, "temperature": 0,
                   "max_tokens": self.runtime.max_tokens, "stream": False}
        mode = self.runtime.decoding
        if mode == "schema":
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}}
        elif mode == "vllm":
            payload["structured_outputs"] = {"json": schema.model_json_schema()}
        elif mode == "json":
            payload["response_format"] = {"type": "json_object"}

        def request():
            started = time.monotonic()
            response = {}
            try:
                response = self.transport(payload)
                choice = response["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("Local VLM output truncated; increase max_tokens")
                return parse_json(choice["message"]["content"], schema)
            finally:
                log_usage("local_vlm", self.model, started, response.get("usage", {}), self.config)
        return with_retries(request, self.config, "local_gameplay_chat")

    def score_windows(self, video_path, candidates, *, peaks=None):
        """Optional peaks are absolute source seconds, one per candidate (or None).

        Otherwise choose the event nearest the midpoint, falling back to midpoint.
        No mutable per-window state: simultaneous requests cannot mix peak hints.
        """
        parsed = [ScoringCandidate.model_validate(c.model_dump() if hasattr(c, "model_dump") else c)
                  for c in candidates]
        if not parsed:
            return []
        duration = video_duration(video_path, self.config.processing_timeout_seconds)
        if any(c.end > duration for c in parsed):
            raise ValueError("candidate extends beyond video duration")
        if peaks is not None and len(peaks) != len(parsed):
            raise ValueError("one peak required per candidate")
        selected = []
        for i, candidate in enumerate(parsed):
            midpoint = (candidate.start + candidate.end) / 2
            events = [e.get("time") for e in candidate.events if isinstance(e, dict)]
            events = [t for t in events if isinstance(t, (float, int)) and not isinstance(t, bool)
                      and math.isfinite(t) and candidate.start <= t < candidate.end]
            peak = peaks[i] if peaks is not None else min(events, key=lambda t: abs(t - midpoint), default=midpoint)
            peak = midpoint if peak is None else peak
            if not math.isfinite(peak) or not candidate.start <= peak < candidate.end:
                raise ValueError("peak must be inside its candidate")
            selected.append(peak - candidate.start)
        prompt = WINDOW_PROMPT.read_text(encoding="utf-8")
        results = []
        for candidate, peak in zip(parsed, selected):
            with video_slice(Path(video_path), candidate.start, candidate.end, self.config.processing_timeout_seconds) as window:
                result = self._infer(window, prompt, WindowAssessment, peak=peak)
            data = result.model_dump()
            if data["player_alive"] is not True:
                data.update(kind="neutral", hype=0.0)
            results.append(ScoredWindow(**candidate.model_dump(), **data))
        return results
