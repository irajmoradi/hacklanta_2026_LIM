"""Persistent fail-closed paid-request counter for the explicitly live demo."""
import json
import threading
from pathlib import Path


class Budget:
    def __init__(self, path, limit=3):
        self.path = Path(path)
        self.limit = min(3, limit)
        self.lock = threading.Lock()

    def reserve(self, model):
        with self.lock:
            rows = json.loads(self.path.read_text()) if self.path.exists() else []
            if len(rows) >= self.limit:
                raise RuntimeError('DEMO-01 live Gemini budget exhausted (3 maximum)')
            rows.append({'attempt': len(rows) + 1, 'model': model})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(rows, indent=2))
            temporary.replace(self.path)
            return len(rows)

    def wrap(self, method):
        def counted(*args, **kwargs):
            self.reserve(kwargs.get('model', 'unknown'))
            return method(*args, **kwargs)
        return counted
