"""Explicit DEMO-02 live smoke. Stock API; durable 80-attempt ceiling."""
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "full_app"))
from werkzeug.serving import make_server
from server.api import create_app


def main():
    assert os.getenv("LIM_DEMO02_LIVE") == "1"
    assert int(os.environ["MAX_GEMINI_CALLS_PER_JOB"]) <= 80
    root = Path("/srv/demo_out/demo02")
    root.mkdir(parents=True, exist_ok=True)
    os.environ["REACTION_PACK"] = "/srv/packs/team"
    app = create_app(dict(WORKSPACE=str(root / "jobs"), JOB_WORKERS=1,
                         STAGE_TIMEOUT_SECONDS=7200, API_RATE_LIMIT=10000))
    # Hosting the unmodified production build is the only demo-specific wiring.
    app.static_folder = str(REPO / "full_app/production_frontend/dist")
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = make_server("127.0.0.1", 8012, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = subprocess.run(["node", str(REPO / "demo_video/record_v2.cjs")])
        raise SystemExit(result.returncode)
    finally:
        marker = root / "job-id.txt"
        if marker.exists():
            ledger = root / "jobs" / marker.read_text().strip() / "gemini-budget.sqlite3"
            if ledger.exists():
                with sqlite3.connect(ledger) as db:
                    used = db.execute("SELECT used FROM budget WHERE id=1").fetchone()[0]
                (root / "live_calls.json").write_text(json.dumps(dict(used=used, limit=80)))
                print("LIVE ATTEMPTS", used, flush=True)
        server.shutdown()
        app.extensions["job_queue"].close()


if __name__ == "__main__":
    main()
