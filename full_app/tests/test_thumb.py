"""Offline image contract, persistent attempt caps and fallback evidence."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from services.call_budget import CallBudget
from services.gemini_client import GeminiProvider
from services.provider_errors import ProviderFailure
from social import build_share_kit
from social.image_candidates import candidates, reaction_frame
from social.thumbnails import SIZES, render_thumbnail
from test_social import job, clips  # synthetic ffmpeg fixtures


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "test-image-model")
    data = io.BytesIO()
    Image.new("RGB", (96, 54), "orange").save(data, format="PNG")
    sdk = Mock()
    sdk.models.generate_content.return_value = SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(
            mime_type="image/png", data=data.getvalue()))]))])
    return GeminiProvider(client=sdk, vertexai=True)


def test_provider_model_mime_and_no_retries(provider, tmp_path):
    reference = tmp_path / "frame.jpg"
    Image.new("RGB", (80, 45)).save(reference)
    output = provider.generate_thumbnail(reference, "no text", tmp_path / "out.jpg")
    with Image.open(output) as image:
        assert image.format == "JPEG" and image.size == (96, 54)
    args = provider.client.models.generate_content.call_args.kwargs
    assert args["model"] == "test-image-model"
    assert args["contents"][0].inline_data.mime_type == "image/png"
    assert args["config"].image_config.aspect_ratio == "16:9"
    assert args["config"].http_options.retry_options.attempts == 1
    assert provider.budget.used == provider.image_budget.used == 1


def test_durable_image_cap_and_failed_attempts(provider, tmp_path):
    reference = tmp_path / "frame.png"
    Image.new("RGB", (80, 45)).save(reference)
    provider.client.models.generate_content.side_effect = TimeoutError("private-key-detail")
    for _ in range(4):
        with pytest.raises(TimeoutError):
            provider.generate_thumbnail(reference, "", tmp_path / "out.png",
                image_budget=CallBudget(tmp_path / "images.sqlite3", limit=4))
    with pytest.raises(ProviderFailure, match="budget"):
        provider.generate_thumbnail(reference, "", tmp_path / "out.png",
            image_budget=CallBudget(tmp_path / "images.sqlite3", limit=4))
    assert provider.client.models.generate_content.call_count == 4
    assert provider.budget.used == 4


def test_shared_budget_blocks_transport(provider, tmp_path):
    provider.budget = CallBudget(limit=0)
    reference = tmp_path / "frame.png"
    Image.new("RGB", (80, 45)).save(reference)
    with pytest.raises(ProviderFailure, match="budget"):
        provider.generate_thumbnail(reference, "", tmp_path / "out.png")
    provider.client.models.generate_content.assert_not_called()


def test_direct_and_share_calls_use_same_job_image_ledger(provider, tmp_path):
    provider.budget = CallBudget(tmp_path / "gemini-budget.sqlite3")
    reference = tmp_path / "frame.png"
    Image.new("RGB", (80, 45)).save(reference)
    # Legacy intro/outro thumbnail calls and share-kit calls share the four slots.
    for _ in range(2):
        provider.generate_thumbnail(reference, "", tmp_path / "out.png")
    for _ in range(2):
        provider.generate_thumbnail(reference, "", tmp_path / "out.png",
            image_budget=CallBudget(tmp_path / "thumbnail-budget.sqlite3", limit=4))
    provider.image_budget = CallBudget(limit=4)  # Simulate a newly constructed client.
    with pytest.raises(ProviderFailure, match="budget"):
        provider.generate_thumbnail(reference, "", tmp_path / "out.png")
    assert provider.client.models.generate_content.call_count == 4


@pytest.mark.parametrize("flag,client_present,reason", [
    (False, True, "disabled"), ("true", True, "disabled"),
    (None, True, "disabled"), (True, False, "client_unavailable"),
])
def test_options_and_job_warnings(job, clips, flag, client_present, reason):
    client = Mock() if client_present else None
    state = {"dir": str(job), "options": {"gemini_image": flag, "mode": "mean"}, "warnings": []}
    kit = build_share_kit(job, clips, {}, "Deadlock", client=client, job=state)
    meta = json.loads((kit / "metadata.json").read_text())
    assert state["warnings"] == meta["warnings"] and len(meta["warnings"]) == 2
    assert all(c["provider"] == "local" and c["reason"] == reason for c in meta["thumbnail_candidates"])
    assert meta["thumbnails"]["youtube"]["text"] == "SKILL ISSUE"
    if client:
        client.generate_thumbnail.assert_not_called()


def test_two_candidates_partial_failure_and_variants(job, clips, provider, caplog):
    response = provider.client.models.generate_content.return_value
    provider.client.models.generate_content.side_effect = [RuntimeError("private-key-detail"), response]
    state = {"dir": str(job), "options": {"gemini_image": True}, "warnings": []}
    kit = build_share_kit(job, clips, {"social": {"thumbnail_text": "ONE TWO THREE FOUR FIVE"}},
                          "Valorant", client=provider, job=state)
    meta = json.loads((kit / "metadata.json").read_text())
    assert meta["selected_thumbnail_candidate"] == 2
    assert len(meta["thumbnail_candidates"]) == 2
    assert meta["thumbnail_candidates"][0]["reason"] == "provider"
    assert len(state["warnings"]) == 1
    assert "private-key-detail" not in caplog.text + json.dumps(meta)
    assert provider.client.models.generate_content.call_count == 2
    for candidate in meta["thumbnail_candidates"]:
        for variant, size in SIZES.items():
            with Image.open(kit / candidate["variants"][variant]["file"]) as image:
                assert image.size == size
    assert meta["thumbnails"]["square"]["text"].replace("\n", " ") == "ONE TWO THREE FOUR"


def test_repeated_candidate_builds_share_persistent_limit(provider, tmp_path):
    frame = Image.new("RGB", (160, 90))
    for _ in range(3):
        warnings = []
        _, results = candidates(frame, {"gemini_image": True}, "Valorant", provider,
                                 tmp_path, tmp_path, warnings)
    assert provider.client.models.generate_content.call_count == 4
    assert all(evidence["reason"] == "budget" for _, evidence in results)
    assert len(warnings) == 2


@pytest.mark.parametrize("parts", [None, [], [SimpleNamespace(inline_data=None)],
    [SimpleNamespace(inline_data=SimpleNamespace(mime_type="text/plain", data=b"bad"))]])
def test_empty_and_nonimage_responses(provider, tmp_path, parts):
    provider.client.models.generate_content.return_value.candidates[0].content = SimpleNamespace(parts=parts)
    reference = tmp_path / "frame.png"
    Image.new("RGB", (80, 45)).save(reference)
    with pytest.raises(RuntimeError, match="did not return an image"):
        provider.generate_thumbnail(reference, "", tmp_path / "out.png")
    assert not (tmp_path / "out.png").exists()


def test_reaction_restricts_pack_and_keeps_alpha(tmp_path, monkeypatch):
    pack = tmp_path / "team"
    pack.mkdir()
    monkeypatch.setattr("social.image_candidates.TEAM_PACK", pack)
    outside = tmp_path / "outsider.alpha.webm"
    outside.touch()
    with pytest.raises(ValueError, match="team-pack"):
        reaction_frame(str(outside), tmp_path / "head.png")
    (pack / "hype.alpha.webm").touch()
    png = io.BytesIO()
    image = Image.new("RGBA", (40, 40))
    image.paste((255, 0, 0, 255), (10, 10, 30, 30))
    image.save(png, format="PNG")
    monkeypatch.setattr("social.image_candidates.probe_media", lambda *a, **k: {"format": {"duration": "2"}})
    run = Mock(return_value=SimpleNamespace(stdout=png.getvalue()))
    monkeypatch.setattr("social.image_candidates.subprocess.run", run)
    evidence = reaction_frame("hype.alpha.webm", tmp_path / "head.png")
    assert evidence["file"] == "hype.alpha.webm" and run.call_count == 4
    with Image.open(tmp_path / "head.png") as output:
        assert output.mode == "RGBA" and output.size == (20, 20)


def test_reaction_failure_is_visible(provider, tmp_path):
    warnings = []
    _, results = candidates(Image.new("RGB", (80, 45)),
        {"gemini_image": True, "reaction_head": "missing.alpha.webm"}, "Deadlock",
        provider, tmp_path, tmp_path, warnings)
    assert warnings == ["Thumbnail reaction unavailable; continuing with gameplay only."]
    assert all(e["provider"] == "gemini" and e["reaction"] is None for _, e in results)


def test_reaction_reference_and_mode_prompt(provider, tmp_path, monkeypatch):
    def extract(name, output):
        Image.new("RGBA", (24, 32), (255, 0, 0, 128)).save(output)
        return {"file": name, "timestamp": .5}
    monkeypatch.setattr("social.image_candidates.reaction_frame", extract)
    warnings = []
    title, results = candidates(Image.new("RGB", (80, 45)),
        {"gemini_image": True, "mode": "mean", "reaction_head": "hype.alpha.webm"},
        "Deadlock", provider, tmp_path, tmp_path, warnings)
    assert not warnings and title == "SKILL ISSUE"
    for call in provider.client.models.generate_content.call_args_list:
        contents = call.kwargs["contents"]
        assert len(contents) == 3
        with Image.open(io.BytesIO(contents[1].inline_data.data)) as image:
            assert image.mode == "RGBA" and image.getchannel("A").getextrema() == (128, 128)
        assert "Deadlock" in contents[-1] and "playful roast" in contents[-1]
        assert "consented teammate" in contents[-1] and "No text" in contents[-1]
    assert all(e["reaction"]["file"] == "hype.alpha.webm" for _, e in results)


def test_plan_flag_overrides_job_default(job, clips, provider):
    state = {"dir": str(job), "options": {"gemini_image": True}}
    build_share_kit(job, clips, {"social": {"gemini_image": False}}, "Valorant", client=provider, job=state)
    provider.client.models.generate_content.assert_not_called()
    assert all("disabled" in warning for warning in state["warnings"])


def test_portrait_keeps_action_and_reaction_in_separate_panels():
    frame = Image.new("RGB", (1600, 900), "red")
    frame.paste("blue", (880, 0, 1600, 900))
    image, details = render_thumbnail(frame, "NO SHOT", SIZES["vertical"],
                                     preserve_scene=True, reaction=True)
    assert details["composition"] == "action_reaction_panels"
    assert image.getpixel((900, 850)) == (255, 0, 0)
    assert image.getpixel((900, 1700)) == (0, 0, 255)
    square, details = render_thumbnail(frame, "NO SHOT", SIZES["square"], preserve_scene=True)
    assert details["composition"] == "full_scene"
    assert square.getpixel((40, 800)) == (255, 0, 0)
    assert square.getpixel((1040, 800)) == (0, 0, 255)
