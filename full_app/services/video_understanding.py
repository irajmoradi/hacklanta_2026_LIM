"""Provider-independent video slicing, structured inference and window scoring."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
import json
import logging
import math
from pathlib import Path
import subprocess
import tempfile
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from models.schemas import ClipList, ScoredWindow, ScoringCandidate, WindowAssessment

LOG = logging.getLogger(__name__)
WINDOW_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "window_scorer.txt"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    chunk_seconds: float = Field(default=600, gt=0)
    overlap_seconds: float = Field(default=10, ge=0)
    fps: float = Field(default=2, gt=0, le=30)
    timeout_seconds: float = Field(default=120, gt=0)
    processing_timeout_seconds: float = Field(default=300, gt=0)
    attempts: int = Field(default=3, ge=1, le=5)
    backoff_seconds: float = Field(default=1, ge=0)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.overlap_seconds >= self.chunk_seconds:
            raise ValueError("overlap must be shorter than chunk")
        return self


def video_duration(path: str | Path, timeout: float = 120) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=timeout,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video must have a finite positive duration")
    return duration


def chunk_ranges(duration: float, size: float, overlap: float):
    if not all(math.isfinite(x) for x in (duration, size, overlap)):
        raise ValueError("chunk settings must be finite")
    if duration <= 0 or size <= 0 or not 0 <= overlap < size:
        raise ValueError("invalid chunk settings")
    start = 0.0
    while start < duration:
        end = min(start + size, duration)
        yield start, end
        if end == duration:
            break
        start = end - overlap


@contextmanager
def video_slice(path, start, end, timeout):
    """Re-encode to reset timestamps exactly, including non-keyframe starts."""
    with tempfile.TemporaryDirectory(prefix="lim-vlm-") as directory:
        output = Path(directory) / "window.mp4"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(start), "-i", str(path), "-t", str(end - start),
             "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-avoid_negative_ts", "make_zero", str(output)],
            capture_output=True, check=True, timeout=timeout,
        )
        yield output


def retryable(error):
    code = getattr(error, "status_code", None) or getattr(error, "code", None)
    if code is not None:
        return str(code) in {"408", "429", "500", "502", "503", "504"}
    return isinstance(error, (TimeoutError, ConnectionError, ValidationError, json.JSONDecodeError))


def with_retries(operation, config, label):
    for attempt in range(config.attempts):
        try:
            return operation()
        except Exception as error:
            if attempt + 1 == config.attempts or not retryable(error):
                raise
            # Deliberately omit exception messages: HTTP errors may contain credentials.
            LOG.warning("vlm retry operation=%s attempt=%d error_type=%s",
                        label, attempt + 1, type(error).__name__)
            time.sleep(config.backoff_seconds * 2 ** attempt)


def log_usage(provider, model, started, usage, config):
    incoming = usage.get("prompt_tokens", 0) or 0
    outgoing = usage.get("completion_tokens", 0) or 0
    cost = None
    if config.input_usd_per_million is not None and config.output_usd_per_million is not None:
        cost = (incoming * config.input_usd_per_million + outgoing * config.output_usd_per_million) / 1e6
    LOG.info("vlm provider=%s model=%s elapsed_seconds=%.3f input_tokens=%s output_tokens=%s estimated_usd=%s",
             provider, model, time.monotonic() - started, incoming, outgoing, cost)


class VideoUnderstandingProvider(ABC):
    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig()

    @abstractmethod
    def _infer(self, video_path: Path, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """Infer one local video with timestamps relative to its first frame."""

    def analyze_video(self, video_path: str | Path, prompt: str = "Find gameplay highlights and lowlights.") -> ClipList:
        path = Path(video_path)
        duration = video_duration(path, self.config.timeout_seconds)
        clips = []
        for start, end in chunk_ranges(duration, self.config.chunk_seconds, self.config.overlap_seconds):
            local_prompt = (
                f"{prompt}\nTIMELINE OVERRIDE: This input is a standalone {end-start:.3f}s video. "
                "Ignore full-source durations/section boundaries above. Cover this entire input; "
                "return local numeric seconds from zero. start_seconds/end_seconds must equal start/end."
            )
            if start == 0 and end == duration:
                result = self._infer(path, local_prompt, ClipList)
            else:
                with video_slice(path, start, end, self.config.processing_timeout_seconds) as chunk:
                    result = self._infer(chunk, local_prompt, ClipList)
            for clip in result.clips:
                if clip.end > end - start + 0.05:
                    raise ValueError("provider returned a clip outside its input timeline")
                data = clip.model_dump()
                for key in ("start", "end", "start_seconds", "end_seconds"):
                    data[key] = min(duration, data[key] + start)
                clips.append(type(clip).model_validate(data))
        # Overlap creates repeated moments. Keep the first complete observation.
        unique = []
        for clip in sorted(clips, key=lambda c: (c.start, c.end)):
            if any(max(0, min(clip.end, old.end) - max(clip.start, old.start)) /
                   min(clip.end - clip.start, old.end - old.start) >= 0.5 for old in unique):
                continue
            unique.append(clip)
        return ClipList(clips=unique)

    def score_windows(self, video_path: str | Path, candidates) -> list[ScoredWindow]:
        parsed = [ScoringCandidate.model_validate(c.model_dump() if isinstance(c, BaseModel) else c)
                  for c in candidates]
        if not parsed:
            return []
        path = Path(video_path)
        duration = video_duration(path, self.config.timeout_seconds)
        # Validate every window before making any paid call.
        if any(c.end > duration for c in parsed):
            raise ValueError("candidate extends beyond video duration")
        prompt = WINDOW_PROMPT.read_text(encoding="utf-8")
        results = []
        for candidate in parsed:
            with video_slice(path, candidate.start, candidate.end, self.config.processing_timeout_seconds) as window:
                assessment = self._infer(window, prompt + "\nCandidate hints: " + candidate.model_dump_json(), WindowAssessment)
            data = assessment.model_dump()
            if data["player_alive"] is not True:
                data.update(kind="neutral", hype=0.0)
            results.append(ScoredWindow(**candidate.model_dump(), **data))
        return results


class MockProvider(VideoUnderstandingProvider):
    """Scripted JSON responses/exceptions with the same validation and retry path."""
    def __init__(self, responses, config=None):
        super().__init__(config)
        self.responses = iter(responses)
        self.calls = []

    def _infer(self, video_path, prompt, schema):
        def request():
            self.calls.append((str(video_path), prompt, schema))
            response = next(self.responses)
            if isinstance(response, Exception):
                raise response
            return schema.model_validate_json(response) if isinstance(response, str) else schema.model_validate(response)
        return with_retries(request, self.config, "mock")
