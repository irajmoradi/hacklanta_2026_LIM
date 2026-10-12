"""Adapt the local video provider to the retained edit planner contract."""
import os
from services.local_vlm import OpenAICompatibleVLMProvider
from services.gemini_client import GeminiVideoClient


class LocalClient(OpenAICompatibleVLMProvider):
    def __init__(self, api_key=None, budget=None):
        super().__init__(os.getenv('LOCAL_VLM_MODEL', 'local'),
                         os.getenv('LOCAL_VLM_URL', 'http://localhost:8000/v1'),
                         api_key=os.getenv('LOCAL_VLM_API_KEY'))
        self.planner_key = api_key
        self.budget = budget

    def upload_video(self, path):
        return path

    def find_clips(self, path, prompt):
        return [c.model_dump() for c in self.analyze_video(path, prompt).clips]

    def plan_edit(self, prompt):
        # Local analysis uses Gemini planning unless the local planner option is enabled.
        with GeminiVideoClient(api_key=self.planner_key) as planner:
            if self.budget is not None:
                planner.budget = self.budget
            return planner.plan_edit(prompt)
