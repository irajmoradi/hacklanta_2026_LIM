"""Offline SDK schema diagnostic: transport is replaced before any request."""
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'full_app'))
from services.gemini_client import GeminiVideoClient
from models.schemas import ClipList, WindowAssessment

if __name__ == '__main__':
    with GeminiVideoClient(api_key='offline-not-a-key', vertexai=True) as client:
        for schema in (WindowAssessment, ClipList):
            try:
                with patch.object(client.client.models._api_client, 'request', side_effect=RuntimeError('OFFLINE: transport reached')):
                    client.client.models.generate_content(model='gemini-3.5-flash-lite', contents=['offline'],
                        config=client._generation_config(schema, .3, True))
            except Exception as exc:
                print(schema.__name__, type(exc).__name__, str(exc), flush=True)
    from live_smoke_server import DemoClient, CombinedAssessment
    with DemoClient('offline-not-a-key') as client:
        with patch.object(client.client.models._api_client, 'request', side_effect=RuntimeError('OFFLINE: transport reached')):
            try:
                # Bypass paid-attempt wrapper: the transport itself is mocked.
                from google.genai.models import Models
                Models.generate_content(client.client.models, model='gemini-3.5-flash-lite', contents=['offline'],
                                        config=client._generation_config(CombinedAssessment, .3, True))
            except Exception as exc:
                print('Demo combined schema', type(exc).__name__, str(exc), flush=True)
