"""Explicit launch recipes and model availability checks; never auto-download."""

import json
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    backend: Literal["vllm", "ollama"] = "vllm"
    model: str = Field(default="Qwen/Qwen2.5-VL-7B-Instruct", min_length=1)
    base_url: str = "http://127.0.0.1:8000/v1"
    decoding: Literal["schema", "vllm", "json", "prompt"] = "schema"
    max_model_len: int = Field(default=16384, ge=2048)
    image_budget: int = Field(default=8, ge=3, le=36)
    max_tokens: int = Field(default=512, ge=64)
    docker_image: str = "vllm/vllm-openai:v0.15.0"

    @model_validator(mode="after")
    def valid_runtime(self):
        from urllib.parse import urlsplit
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("base_url must be an HTTP(S) API root without credentials/query")
        if self.max_tokens >= self.max_model_len:
            raise ValueError("leave context space for images and prompts")
        if self.backend == "ollama" and self.decoding == "vllm":
            raise ValueError("vllm decoding requires vLLM")
        return self

    def launch_commands(self):
        """Argument lists suitable for subprocess (shell=False) or shlex.join."""
        if self.backend == "ollama":
            return [["ollama", "serve"], ["ollama", "pull", self.model], ["ollama", "run", self.model]]
        return [["docker", "run", "--rm", "--gpus", "all", "--ipc=host",
                 "-p", "127.0.0.1:8000:8000", "-v", "lim-vlm-models:/root/.cache/huggingface",
                 self.docker_image, "--model", self.model, "--max-model-len", str(self.max_model_len),
                 "--limit-mm-per-prompt", json.dumps({"image": self.image_budget}),
                 "--gpu-memory-utilization", "0.85", "--max-num-seqs", "1"]]


def health_check(runtime, *, api_key=None, timeout=5):
    """Check /models for the configured ID; this does not run generation."""
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    try:
        with urlopen(Request(runtime.base_url.rstrip("/") + "/models", headers=headers), timeout=timeout) as response:
            models = json.load(response)
        available = any(item.get("id") == runtime.model for item in models["data"])
        return {"ok": available, "model": runtime.model,
                "detail": "model available" if available else "configured model is not listed"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        # Avoid exposing keys, URLs with sensitive content, or server error bodies.
        return {"ok": False, "model": runtime.model, "detail": type(error).__name__}
