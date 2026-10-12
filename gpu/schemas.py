"""Bounded wire contracts, independent of Modal and model frameworks."""
import base64
import io
from typing import Annotated

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BODY = 18 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
MODEL_ID = "facebook/vjepa2-vitl-fpc64-256"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def binary(value, limit):
    if len(value) > ((limit + 2) // 3) * 4:
        raise ValueError("Encoded media too large")
    data = base64.b64decode(value, validate=True)
    if not data or len(data) > limit:
        raise ValueError("Invalid media size")
    return data


def png(value):
    data = binary(value, 256 * 256 * 4)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or not (1 <= image.width <= 256 and 1 <= image.height <= 256):
            raise ValueError("Expected PNG at most 256x256")
        return np.array(image.convert("RGB"))


Prompt = Annotated[str, Field(min_length=1, max_length=160, pattern=r"\S")]


class SegmentRequest(Contract):
    image_png: str
    prompt: Prompt


class TrackRequest(Contract):
    frames_png: list[str] = Field(min_length=2, max_length=48)
    fps: float = Field(gt=0, le=60)
    prompt: Prompt


class TranscribeRequest(Contract):
    pcm_f32le: str
    sample_rate: int = Field(default=16000, ge=16000, le=16000)


class EmbedRequest(Contract):
    rgb_u8: str
    frames: int = Field(ge=16, le=64)
    encoder: str = Field(min_length=1, max_length=200)


REQUESTS = {"segment": SegmentRequest, "track": TrackRequest,
            "transcribe": TranscribeRequest, "embed": EmbedRequest}


def decode(kind, request):
    if kind == "segment":
        return png(request.image_png)
    if kind == "track":
        frames = [png(value) for value in request.frames_png]
        if any(frame.shape != frames[0].shape for frame in frames):
            raise ValueError("Frame dimensions differ")
        if len(frames) / request.fps > 12:
            raise ValueError("Track duration exceeds 12 seconds")
        return np.stack(frames)
    if kind == "transcribe":
        samples = np.frombuffer(binary(request.pcm_f32le, 60 * 16000 * 4), dtype="<f4")
        if not np.isfinite(samples).all() or np.any(np.abs(samples) > 1):
            raise ValueError("Expected finite normalized PCM")
        return samples
    if request.frames % 2:
        raise ValueError("Frame count must be even")
    return np.frombuffer(binary(request.rgb_u8, 64 * 256 * 256 * 3), dtype=np.uint8).reshape(
        request.frames, 256, 256, 3)


class Word(Contract):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=500)
    probability: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Invalid word interval")
        return self


def validate_response(kind, result, request, media):
    """Validate outputs against inputs before exposing them to clients."""
    if kind == "segment":
        mask = np.asarray(result["mask"])
        if mask.shape != media.shape[:2] or not np.isin(mask, [0, 1]).all():
            raise ValueError("Invalid mask")
    elif kind == "transcribe":
        if len(result["words"]) > 2000:
            raise ValueError("Too many words")
        previous = 0
        for value in result["words"]:
            word = Word.model_validate(value)
            if word.start < previous or word.end > len(media) / 16000 + .05:
                raise ValueError("Word outside audio timeline")
            previous = word.start
    elif kind == "embed":
        vector = np.asarray(result["features"])
        if result["encoder"] != request.encoder or vector.shape != (1024,) or not np.isfinite(vector).all():
            raise ValueError("Invalid encoder output")
    else:
        rows = result["frames"]
        if len(rows) != len(media):
            raise ValueError("Missing tracked frames")
        h, w = media.shape[1:3]
        if result["width"] != w or result["height"] != h:
            raise ValueError("Invalid track dimensions")
        for index, row in enumerate(rows):
            if row["frame_index"] != index or row["time"] != index / request.fps:
                raise ValueError("Invalid track timeline")
            ids = set()
            if len(row["objects"]) > 32:
                raise ValueError("Too many objects")
            for obj in row["objects"]:
                if type(obj["id"]) is not int or obj["id"] in ids:
                    raise ValueError("Invalid track ID")
                ids.add(obj["id"])
                counts = obj["rle"]
                if not counts or any(type(n) is not int or n < 0 for n in counts) or sum(counts) != h*w:
                    raise ValueError("Invalid row-major RLE")
                box = obj["box"]
                if len(box) != 4 or not (0 <= box[0] <= box[2] <= 1 and 0 <= box[1] <= box[3] <= 1):
                    raise ValueError("Invalid normalized box")
    return result
