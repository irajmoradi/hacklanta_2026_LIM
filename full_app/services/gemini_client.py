"""Gemini API client — video upload, clip finding, edit planning."""

import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from models.schemas import ClipList, EditPlan


class GeminiVideoClient:
    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite-preview"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def upload_video(self, video_path: str | Path) -> object:
        """Upload via File API and wait for processing."""
        uploaded = self.client.files.upload(file=str(video_path))
        while uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = self.client.files.get(name=uploaded.name)
        if uploaded.state.name == "FAILED":
            raise RuntimeError("Gemini failed to process the video file")
        return uploaded

    def find_clips(self, uploaded_file, prompt: str) -> list[dict]:
        """Stage 1: Identify highlight/lowlight clips from the video."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=[uploaded_file, prompt],
            config={
                "response_mime_type": "application/json",
                "response_json_schema": ClipList.model_json_schema(),
                "temperature": 0.3,
            },
        )
        data = json.loads(response.text)
        # Handle both {"clips": [...]} wrapper and bare [...]
        if isinstance(data, dict) and "clips" in data:
            return data["clips"]
        return data

    def plan_edit(self, prompt: str) -> dict:
        """Stage 2: Plan the edit (text-only, no video needed)."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config={
                "response_mime_type": "application/json",
                "response_json_schema": EditPlan.model_json_schema(),
                "temperature": 0.7,
            },
        )
        return json.loads(response.text)
