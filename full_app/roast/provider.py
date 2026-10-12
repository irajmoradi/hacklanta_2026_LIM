"""Injected Gemini adapter. No client construction, credentials or network on import."""

import json

from .safety import WORDS


class GeminiLines:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def __call__(self, kinds: list[str], intensity: int) -> list[str]:
        response = self.client.models.generate_content(
            model=self.model,
            contents=("Write one short funny gameplay roast per event in order. "
                      "Only criticize the shot, aim, timing or game event. No people, identity, "
                      "slurs, threats, appearance or personal traits. Intensity 1 gentle, 2 spicy, "
                      "3 extra playful. Start each line with a gameplay noun. Max 80 ASCII "
                      "characters per line. Use only these words: " + " ".join(sorted(WORDS)) +
                      "\nReturn a JSON array of strings. Events: " + json.dumps(kinds) +
                      f"\nIntensity: {intensity}"),
            config={"response_mime_type": "application/json", "temperature": 0.8,
                    "max_output_tokens": 2048},
        )
        return json.loads(response.text)
