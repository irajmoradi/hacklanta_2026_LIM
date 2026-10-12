"""Deterministic, local gameplay candidate detection (no network/API calls)."""

from .detector import detect_candidates
from .models import Candidate, Config

__all__ = ["Candidate", "Config", "detect_candidates"]
