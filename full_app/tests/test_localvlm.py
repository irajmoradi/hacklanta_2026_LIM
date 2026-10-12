import io
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
import pytest
from pydantic import ValidationError

from localvlm import LocalVLMProvider, RuntimeConfig, SamplerConfig, HUDRegion, health_check
from localvlm.prompts import parse_json
from localvlm.sampling import sample_frames, sample_times
from models.schemas import WindowAssessment
from services.video_understanding import ProviderConfig


CONNECT = socket.socket.connect
CREATE_CONNECTION = socket.create_connection
ANSWER = dict(player_alive=True, kind="highlight", hype=8.0, caption="Clean finish", reaction="sick_kill")


@pytest.fixture
def server(monkeypatch):
    """Real HTTP on an ephemeral loopback port; all other network stays blocked."""
    state = {"requests": [], "status": 200, "delay": 0, "text": json.dumps(ANSWER), "models": ["test-model"]}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["get"] = (self.path, dict(self.headers))
            self.respond({"data": [{"id": name} for name in state["models"]]})

        def do_POST(self):
            state["requests"].append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.respond({"choices": [{"finish_reason": state.get("finish", "stop"),
                                       "message": {"content": state["text"]}}]})

        def respond(self, data):
            time.sleep(state["delay"])
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps(data).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    address = http.server_address

    def connect(sock, target):
        assert target == address, "Only this test's mock server is allowed"
        return CONNECT(sock, target)

    def create_connection(target, *args, **kwargs):
        assert target == address, "Only this test's mock server is allowed"
        return CREATE_CONNECTION(target, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{address[1]}/v1"
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def provider(server, **kwargs):
    return LocalVLMProvider(RuntimeConfig(model="test-model", base_url=server["url"], **kwargs),
                            config=ProviderConfig(attempts=1, backoff_seconds=0), api_key="test-key")


def candidate(start=1., end=4.):
    return dict(start=start, end=end, score=.8, signals={"motion": .9}, events=[{"time": 2.25}])


def test_http_request_scoring_and_hud(server, video):
    result = provider(server).score_windows(video, [candidate()])[0]
    assert result.start == 1 and result.end == 4 and result.hype == 8
    path, headers, body = server["requests"][0]
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == "Bearer test-key"
    assert body["model"] == "test-model" and body["temperature"] == 0
    assert body["max_tokens"] == 512 and body["stream"] is False
    assert body["response_format"]["json_schema"]["schema"] == WindowAssessment.model_json_schema()
    assert len(body["messages"]) == 6  # system, two few-shot pairs, actual input
    content = body["messages"][-1]["content"]
    images = [c for c in content if c["type"] == "image_url"]
    assert len(images) == 8
    assert all(c["image_url"]["url"].startswith("data:image/jpeg;base64,") for c in images)
    assert any("timestamp_seconds=1.250 view=HUD:" in c.get("text", "") for c in content)


@pytest.mark.parametrize("mode,field", [("vllm", "structured_outputs"), ("json", "response_format"), ("prompt", None)])
def test_decoding_modes(server, video, mode, field):
    provider(server, decoding=mode)._infer(video, "score", WindowAssessment)
    body = server["requests"][0][2]
    if field:
        assert field in body
    else:
        assert "response_format" not in body and "structured_outputs" not in body


@pytest.mark.parametrize("wrapper", ["```json\n%s\n```", "Here is the result: %s", "%s"])
def test_json_repair(wrapper):
    text = json.dumps({**ANSWER, "caption": 'literal ,} and \\" text'})
    text = text[:-1] + ",}"
    assert parse_json(wrapper % text, WindowAssessment).caption == 'literal ,} and \\" text'


@pytest.mark.parametrize("changes", [{"hype": 11}, {"player_alive": "true"}, {"reaction": "unknown"}, {"extra": 1}])
def test_repair_does_not_invent_or_coerce(changes):
    with pytest.raises(ValidationError):
        parse_json(json.dumps({**ANSWER, **changes}), WindowAssessment)


def test_reject_ambiguous_and_incomplete_json():
    with pytest.raises(ValueError):
        parse_json(json.dumps(ANSWER) + json.dumps(ANSWER), WindowAssessment)
    with pytest.raises(ValueError):
        parse_json('{"hype":', WindowAssessment)


def test_response_repair_and_spectator_gate(server, video):
    server["text"] = "```json\n" + json.dumps({**ANSWER, "player_alive": None})[:-1] + ",}\n```"
    result = provider(server).score_windows(video, [candidate()], peaks=[2.])[0]
    assert result.kind == "neutral" and result.hype == 0


def test_timeout_is_bounded_and_retried(server, video):
    server["delay"] = .2
    client = provider(server)
    client.config = ProviderConfig(timeout_seconds=.05, attempts=2, backoff_seconds=0)
    with pytest.raises((TimeoutError, ConnectionError)):
        client._infer(video, "score", WindowAssessment)
    assert len(server["requests"]) == 2


def test_http_400_not_retried(server, video):
    from urllib.error import HTTPError
    server["status"] = 400
    client = provider(server)
    client.config = ProviderConfig(attempts=3, backoff_seconds=0)
    with pytest.raises(HTTPError):
        client._infer(video, "score", WindowAssessment)
    assert len(server["requests"]) == 1


def test_invalid_schema_retried(server, video):
    server["text"] = '{"hype": 100}'
    client = provider(server)
    client.config = ProviderConfig(attempts=2, backoff_seconds=0)
    with pytest.raises(ValidationError):
        client._infer(video, "score", WindowAssessment)
    assert len(server["requests"]) == 2


def test_truncated_output_is_rejected(server, video):
    server["finish"] = "length"
    with pytest.raises(ValueError, match="truncated"):
        provider(server)._infer(video, "score", WindowAssessment)


def test_health_and_model_missing(server):
    runtime = RuntimeConfig(model="test-model", base_url=server["url"])
    assert health_check(runtime, api_key="test-key")["ok"]
    assert server["get"][0] == "/v1/models"
    server["models"] = []
    assert not health_check(runtime)["ok"]
    server["status"] = 503
    assert health_check(runtime)["detail"] == "HTTPError"
    assert not server["requests"]


def test_health_timeout(server):
    server["delay"] = .2
    assert not health_check(RuntimeConfig(base_url=server["url"]), timeout=.02)["ok"]


def test_sampler_images_and_bounds(video):
    samples = list(sample_frames(video, 6, 2.25))
    assert len(samples) == 8
    assert [s.timestamp for s in samples] == sorted(s.timestamp for s in samples)
    assert {s.timestamp for s in samples if s.label.startswith("HUD")} == {2.25}
    sizes = [Image.open(io.BytesIO(s.jpeg)).size for s in samples]
    assert all(w == 640 for w, h in sizes)
    assert len(set(sizes)) > 1  # crops retain their own aspect ratios
    for duration, peak in [(.04, 0), (6, 0), (6, 5.999)]:
        times = sample_times(duration, peak, SamplerConfig())
        assert 0 <= min(times) <= max(times) < duration and len(times) <= 6


def test_config_and_launch():
    command = RuntimeConfig().launch_commands()[0]
    assert "127.0.0.1:8000:8000" in command
    assert json.loads(command[command.index("--limit-mm-per-prompt") + 1]) == {"image": 8}
    assert "16384" in command and "--trust-remote-code" not in command
    assert RuntimeConfig(backend="ollama", model="qwen2.5vl:7b").launch_commands() == [
        ["ollama", "serve"], ["ollama", "pull", "qwen2.5vl:7b"], ["ollama", "run", "qwen2.5vl:7b"]]
    with pytest.raises(ValueError):
        LocalVLMProvider(RuntimeConfig(image_budget=3))
    with pytest.raises(ValueError):
        HUDRegion(name="bad", x=.9, y=0, width=.5, height=.5)
    with pytest.raises(ValueError):
        sample_times(3, float("nan"), SamplerConfig())


def test_validate_all_candidates_before_request(server, video):
    client = provider(server)
    for candidates, peaks in [([candidate(), candidate(end=20.)], None),
                               ([candidate()], [4.]), ([candidate()], []),
                               ([candidate()], [float("nan")])]:
        with pytest.raises(ValueError):
            client.score_windows(video, candidates, peaks=peaks)
    assert client.score_windows(video, []) == []
    assert not server["requests"]


def test_inherited_analyze_contract(server, video):
    server["text"] = json.dumps({"clips": [{"start": 1., "end": 2., "start_seconds": 1.,
        "end_seconds": 2., "type": "good", "description": "Confirmed elimination"}]})
    result = provider(server).analyze_video(video)
    assert len(result.clips) == 1 and result.clips[0].start == 1.


def test_cli_health_and_launch(server, monkeypatch, capsys):
    from localvlm.__main__ import main
    monkeypatch.setattr("sys.argv", ["localvlm", "health", "--url", server["url"], "--model", "test-model"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    server["models"] = []
    assert main() == 1
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["localvlm", "launch", "--backend", "ollama"])
    assert main() == 0
    assert "ollama pull qwen2.5vl:7b" in capsys.readouterr().out
