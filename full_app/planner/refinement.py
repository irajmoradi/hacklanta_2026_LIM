"""Opt-in caption refinement. No SDK import, implicit client, retry, or paid call."""

from pathlib import Path
from typing import Protocol

from pydantic import Field

from .models import Model, RenderPlan


class CaptionPatch(Model):
    text_index: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=240)


class Refinement(Model):
    captions: list[CaptionPatch] = Field(default_factory=list)


class Refiner(Protocol):
    def __call__(self, prompt: str) -> str | dict: ...


class GeminiRefiner:
    """Supply your own configured genai.Client and model; one call per invocation."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def __call__(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model, contents=[prompt], config={
                "response_mime_type": "application/json",
                "response_json_schema": Refinement.model_json_schema(),
                "temperature": 0.3,
            },
        )
        return response.text


def refine_captions(plan: RenderPlan, refiner: Refiner) -> RenderPlan:
    """Apply the entire patch or fall back; creative output cannot alter timing."""
    try:
        template = (Path(__file__).resolve().parents[1] / "prompts" / "editor_v2.txt").read_text(encoding="utf-8")
        response = refiner(template + "\n\nRenderPlan data:\n" + plan.model_dump_json())
        patch = Refinement.model_validate_json(response) if isinstance(response, str) else Refinement.model_validate(response)
        result = plan.model_copy(deep=True)
        seen = set()
        for item in patch.captions:
            if item.text_index >= len(result.text) or item.text_index in seen:
                raise ValueError("invalid or duplicate caption index")
            seen.add(item.text_index)
            result.text[item.text_index].content = item.content
        return RenderPlan.model_validate(result.model_dump())
    except Exception:
        # Provider errors can contain credentials or private data; never echo them.
        result = plan.model_copy(deep=True)
        result.notes.append("Optional refinement failed validation or was unavailable; deterministic plan retained.")
        return result
