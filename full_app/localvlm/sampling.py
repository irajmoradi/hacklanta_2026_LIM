"""Bounded, timestamped gameplay images using the app's existing ffmpeg dependency."""

from dataclasses import dataclass
import math
import subprocess

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HUDRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    name: str = Field(min_length=1)
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def in_frame(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("HUD region extends beyond frame")
        return self


class SamplerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    frames: int = Field(default=6, ge=3, le=32)
    width: int = Field(default=640, ge=64, le=1920)
    peak_radius: float = Field(default=0.5, gt=0)
    hud_regions: tuple[HUDRegion, ...] = (
        HUDRegion(name="kill_feed", x=.65, y=0, width=.35, height=.35),
        HUDRegion(name="player_status", x=0, y=.75, width=.5, height=.25),
    )

    @model_validator(mode="after")
    def bounded_hud(self):
        if len(self.hud_regions) > 4:
            raise ValueError("at most four HUD crops are supported")
        return self

    @property
    def image_budget(self):
        return self.frames + len(self.hud_regions)


@dataclass(frozen=True)
class Sample:
    timestamp: float
    label: str
    jpeg: bytes


def sample_times(duration, peak, config):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if peak is None:
        peak = duration / 2
    if not math.isfinite(peak) or not 0 <= peak < duration:
        raise ValueError("peak must be inside the window")
    # Stay clear of EOF even on short, low-FPS clips. Seeking is accurate decode,
    # not restricted to codec I-frames (gameplay events rarely align with those).
    last = max(0, duration - min(.1, duration / 2))
    clamp = lambda t: max(0, min(last, t))
    times = {clamp(peak), clamp(peak - config.peak_radius), clamp(peak + config.peak_radius)}
    # Allocate remaining slots to context, including both ends before interiors.
    context = [0, last] + [last * i / (config.frames - 1) for i in range(1, config.frames - 1)]
    for timestamp in context:
        if len(times) >= config.frames:
            break
        times.add(timestamp)
    return sorted(times)


def sample_frames(path, duration, peak=None, config=None, timeout=30):
    config = config or SamplerConfig()
    times = sample_times(duration, peak, config)
    anchor = min(times, key=lambda t: abs(t - (duration / 2 if peak is None else peak)))
    for timestamp in times:
        regions = [None] + (list(config.hud_regions) if timestamp == anchor else [])
        for region in regions:
            filters = []
            if region:
                filters.append(f"crop=iw*{region.width}:ih*{region.height}:iw*{region.x}:ih*{region.y}")
            filters.append(f"scale={config.width}:-2")
            result = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", str(timestamp),
                 "-i", str(path), "-frames:v", "1", "-vf", ",".join(filters),
                 "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                capture_output=True, check=True, timeout=timeout,
            )
            if not result.stdout:
                raise ValueError("Could not decode gameplay frame")
            yield Sample(timestamp, "full_frame" if region is None else "HUD:" + region.name, result.stdout)
