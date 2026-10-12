"""Synthetic upload -> mocked analysis/plan -> real ffmpeg render regression."""

from unittest.mock import Mock

from .synthetic import generate


def test_app_pipeline(tmp_path, monkeypatch):
    # Prevent environment credentials from initializing any real provider.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    import app as application

    generate(tmp_path / "fixtures")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(application, "WORKSPACE", workspace)
    monkeypatch.setattr(application, "jobs", {})
    provider = Mock()
    provider.find_clips.return_value = [
        {"start": 1, "end": 2, "start_seconds": 1, "end_seconds": 2,
         "type": "good", "description": "Synthetic highlight"}]
    provider.plan_edit.return_value = {"segments": [
        {"source_start": 1, "source_end": 2, "video_effects": ["none"],
         "speed": 1, "transition_in": "cut", "sound_effects": []}]}
    monkeypatch.setattr(application, "gemini", provider)
    client = application.app.test_client()
    with (tmp_path / "fixtures" / "bursts.mp4").open("rb") as source:
        uploaded = client.post("/api/upload", data={"video": (source, "synthetic.mp4")})
    assert uploaded.status_code == 200, uploaded.get_data(as_text=True)
    job_id = uploaded.json["job_id"]
    for endpoint in ("analyze", "plan", "render"):
        response = client.post(f"/api/{endpoint}", json={"job_id": job_id, "generate_thumbnails": False})
        assert response.status_code == 200, response.get_data(as_text=True)
    downloaded = client.get(f"/api/download/{job_id}")
    assert downloaded.status_code == 200
    assert downloaded.mimetype == "video/mp4"
    assert len(downloaded.data) > 1000
    assert client.get(f"/api/status/{job_id}").json["status"] == "done"
    provider.find_clips.assert_called_once()
    provider.plan_edit.assert_called_once()
