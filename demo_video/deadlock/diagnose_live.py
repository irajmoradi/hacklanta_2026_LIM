"""Explicit live diagnostic, one attempt on the same durable task ledger.

Print exception types/stack locations only, never provider exception messages.
"""
import json
import os
from pathlib import Path
import traceback

from profiles import get_profile
from services.call_budget import CallBudget
from services.gemini_client import GeminiVideoClient
from services.video_understanding import ProviderConfig


def main():
    assert os.environ.get('DEADLOCK_LIVE_SMOKE') == '1'
    root = Path('/srv/demo_out/deadlock')
    job = root/'jobs'/(root/'job-id.txt').read_text().strip()
    chunk = next(job.glob('ingest/*/chunks-480-*/00001.mp4'))
    client = GeminiVideoClient(config=ProviderConfig(attempts=1))
    client.auto_proxy = True
    client.budget = CallBudget(job/'gemini-budget.sqlite3', limit=50)
    try:
        clips = client.find_clips(client.upload_video(chunk),
            'Find gameplay highlights and lowlights in this complete input. Return local numeric seconds from zero. '
            + get_profile('deadlock').prompt_fragment())
        (root/'diagnostic-last-clips.json').write_text(json.dumps(clips, indent=2))
        print(json.dumps(dict(success=True, clips=len(clips), remaining=client.budget.remaining)), flush=True)
    except Exception as error:
        print(json.dumps(dict(success=False, error_type=type(error).__name__,
            stack=[dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                   for f in traceback.extract_tb(error.__traceback__)],
            remaining=client.budget.remaining)), flush=True)
        raise SystemExit(1) from None
    finally:
        client.close()


if __name__ == '__main__':
    main()
