"""Opt-in paid smoke test: exactly one generate_content attempt, never automatic."""

import os

import pytest


@pytest.mark.live
@pytest.mark.skipif(os.getenv("LIM_LIVE_SMOKE") != "1", reason="Set LIM_LIVE_SMOKE=1 to authorize one paid call")
def test_gemini_video_live(video):
    from dotenv import load_dotenv
    from services.gemini_client import GeminiProvider
    from services.video_understanding import ProviderConfig

    # Optional path is read at runtime only; neither key nor env file is copied.
    if os.getenv("LIM_LIVE_ENV_FILE"):
        load_dotenv(os.environ["LIM_LIVE_ENV_FILE"], override=False)
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        pytest.skip("No runtime credentials")
    with GeminiProvider(config=ProviderConfig(attempts=1)) as provider:
        result = provider.analyze_video(video, "This is a synthetic test pattern, not gameplay. Return an empty clips array.")
        assert result.clips == []
