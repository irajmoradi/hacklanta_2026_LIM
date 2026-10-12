import socket
import subprocess

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "live: explicitly enabled paid Gemini smoke test")


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return
    def blocked(*args, **kwargs):
        raise AssertionError("Network is forbidden in non-live tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "synthetic.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True, timeout=30)
    return path
