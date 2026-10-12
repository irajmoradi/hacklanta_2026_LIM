"""Opt-in local gameplay video understanding; no model downloads on import."""

from .provider import LocalVLMProvider
from .runtime import RuntimeConfig, health_check
from .sampling import HUDRegion, SamplerConfig

__all__ = ["LocalVLMProvider", "RuntimeConfig", "health_check", "HUDRegion", "SamplerConfig"]
