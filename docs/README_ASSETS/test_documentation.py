"""DOC-01 drift checks and executable, provider-free quickstart verification.

Run from the worktree root with the core app requirements and pytest installed.
All media and subprocess working files are generated in pytest temporary paths.
"""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "full_app"
QUICKSTART = (ROOT / "docs/quickstart.md").read_text(encoding="utf-8-sig")
DOCS = [ROOT / "README.md", ROOT / "docs/architecture.md", ROOT / "docs/quickstart.md"]


def source_trees():
    for path in APP.rglob("*.py"):
        if any(part in {".venv", "workspace", "node_modules", "__pycache__"} for part in path.parts):
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8-sig"))


def test_relative_document_links_exist():
    for path in DOCS:
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8-sig")):
            if "://" in target or target.startswith("#"):
                continue
            assert (path.parent / target.split("#", 1)[0]).exists(), (path, target)


def test_environment_inventory_matches_python_reads():
    names = set()
    for _, tree in source_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in {"os.getenv", "os.environ.get"}:
                # A conditional key expression (Vertex) has two constant names.
                if node.args:
                    names.update(n.value for n in ast.walk(node.args[0])
                                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                                 and re.fullmatch(r"[A-Z][A-Z0-9_]+", n.value))
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                if isinstance(node.slice, ast.Constant):
                    names.add(node.slice.value)
    assert names
    assert not (names - set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", QUICKSTART)))


def cli_sources():
    for path, tree in source_trees():
        switches = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                switches.update(arg.value for arg in node.args if isinstance(arg, ast.Constant)
                                and isinstance(arg.value, str) and arg.value.startswith("--"))
        if switches:
            parts = list(path.relative_to(APP).with_suffix("").parts)
            if parts[-1] == "__main__":
                parts.pop()
            yield ".".join(parts), switches


@pytest.mark.parametrize("module,switches", list(cli_sources()))
def test_cli_inventory_and_help(module, switches):
    row = next(line for line in QUICKSTART.splitlines()
               if line.startswith(f"| `python -m {module}` |"))
    assert switches <= set(re.findall(r"--[a-z][a-z-]*", row)), module
    result = subprocess.run([sys.executable, "-m", module, "--help"], cwd=APP,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert switches <= set(re.findall(r"--[a-z][a-z-]*", result.stdout))


def test_http_option_inventory():
    tree = ast.parse((APP / "server/validation.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "options_valid")
    assignment = next(node for node in function.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "allowed" for t in node.targets))
    names = ast.literal_eval(assignment.value)
    table = QUICKSTART.split("| HTTP option / flag |", 1)[1].split("## Explicit", 1)[0]
    assert names <= set(re.findall(r"`([a-z_]+)`", table))


def test_quickstart_shell_upload_render_download(tmp_path, monkeypatch):
    # Execute the published Bash snippets against a real local HTTP server.
    # Fail immediately if an accidental change attempts any provider operation.
    sys.path.insert(0, str(APP))
    from pipeline.orchestrator import Pipeline
    from server.api import create_app
    from werkzeug.serving import make_server

    def no_provider(*args, **kwargs):
        raise AssertionError("The documented render check must never call a provider")

    monkeypatch.setattr(Pipeline, "client", no_provider)
    monkeypatch.setattr("google.genai.Client", no_provider)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "REACTION_PACK"):
        monkeypatch.delenv(key, raising=False)
    app = create_app({"TESTING": True, "WORKSPACE": str(tmp_path / "jobs")})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    section = QUICKSTART.split("## Key-free render check", 1)[1].split("## Docker", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)\n```", section, re.S)
    assert len(blocks) == 2
    environment = dict(os.environ)
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment["PATH"]
    try:
        first = subprocess.run(["bash", "-euc", blocks[0].replace("http://localhost:8000", base)],
                               cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60)
        assert first.returncode == 0, first.stderr
        job_id = json.loads((tmp_path / "full_app/workspace/doc-smoke/job.json").read_text())["id"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with urlopen(f"{base}/api/jobs/{job_id}", timeout=5) as response:
                snapshot = json.load(response)
            assert snapshot["status"] != "error", snapshot
            if snapshot["status"] == "done":
                break
            time.sleep(.1)
        else:
            pytest.fail("Render did not finish within 60 seconds")
        environment["JOB_ID"] = job_id
        second = subprocess.run(["bash", "-euc", blocks[1].replace("http://localhost:8000", base)],
                                cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
        assert second.returncode == 0, second.stderr
        streams = json.loads(second.stdout)["streams"]
        assert any(s.get("width") == 1280 and s.get("height") == 720 for s in streams)
        assert {s["codec_name"] for s in streams} >= {"h264", "aac"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.extensions["job_queue"].close()
