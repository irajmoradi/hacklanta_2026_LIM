"""Validated API payloads. Coordinates are normalized; times are source seconds."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Box(Model):
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def bounds(self):
        if self.x + self.width > 1.000000001 or self.y + self.height > 1.000000001:
            raise ValueError("box extends beyond frame")
        return self


class BlurBox(Box):
    start: float = Field(default=0, ge=0)
    end: float = Field(gt=0)
    kind: str = "manual"

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("end must follow start")
        return self


class PrivacyOptions(Model):
    game: str = "valorant"
    backend: Literal["auto", "tesseract", "rapidocr", "none"] = "auto"
    own_name: str | None = Field(default=None, max_length=100)
    keep_own_name: bool = False
    blur_webcam: bool = False
    sample_fps: float = Field(default=2, ge=0.2, le=10)
    hold_seconds: float = Field(default=0.75, ge=0, le=5)
    padding_pixels: int = Field(default=5, ge=0, le=100)
    # EXT-09/profile callers can supply normalized named regions here.
    regions: dict[str, Box] | None = None
    manual_boxes: list[BlurBox] = Field(default_factory=list, max_length=500)


class BlurTrack(Model):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration: float = Field(gt=0)
    boxes: list[BlurBox] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def within_duration(self):
        if any(b.end > self.duration + 1e-6 for b in self.boxes):
            raise ValueError("blur box exceeds source duration")
        return self
