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

    def delete_file(self, uploaded_file) -> None:
        """Delete an uploaded file from Gemini storage."""
        try:
            self.client.files.delete(name=uploaded_file.name)
            print(f"  [gemini] Deleted {uploaded_file.name}")
        except Exception as e:
            print(f"  [gemini] Failed to delete {uploaded_file.name}: {e}")

    def find_clips(self, uploaded_file, prompt: str) -> list[dict]:
        """Stage 1: Identify highlight/lowlight clips from the video."""
        try:
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
            if isinstance(data, dict) and "clips" in data:
                return data["clips"]
            return data
        finally:
            self.delete_file(uploaded_file)

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

    def generate_thumbnail(self, image_path: str | Path, prompt: str,
                           output_path: str | Path) -> Path:
        """Generate a thumbnail image using Gemini image generation."""
        output_path = Path(output_path)
        with open(image_path, "rb") as f:
            img_bytes = f.read()

        response = self.client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                return output_path

        raise RuntimeError("Gemini did not return an image")
