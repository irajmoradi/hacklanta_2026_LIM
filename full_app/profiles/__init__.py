"""Shared, offline game profiles for candidate detection and VLM scoring."""
from .registry import Box, GameProfile, get_profile, list_profiles, match_events
from .detection import OCRToken, detect_game, detect_frames

__all__ = ["Box", "GameProfile", "OCRToken", "get_profile", "list_profiles",
           "match_events", "detect_game", "detect_frames"]
