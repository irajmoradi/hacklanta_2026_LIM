"""AI Gameplay Clip Editor HTTP entry point."""
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from server.api import create_app

app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # One process owns the durable queue; disable the development reloader.
    app.run(port=8000, host="127.0.0.1", threaded=True, use_reloader=False)
