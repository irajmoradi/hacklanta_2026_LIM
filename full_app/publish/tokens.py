"""Encrypted local OAuth credentials; encryption is an opt-in dependency."""
import json
import os
from pathlib import Path
import tempfile

from .common import PublishError


class TokenStore:
    def __init__(self, directory=None):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise PublishError("Install publish/requirements.txt for token storage") from None
        try:
            self._cipher = Fernet(os.environ["PUBLISH_TOKEN_KEY"].encode())
        except (KeyError, ValueError):
            raise PublishError("Set PUBLISH_TOKEN_KEY to a Fernet key") from None
        self.directory = Path(directory or Path.home() / ".lim-publish")

    def _path(self, provider):
        if provider not in ("youtube", "tiktok"):
            raise ValueError("Unknown provider")
        return self.directory / (provider + ".enc")

    def save(self, provider, tokens):
        path = self._path(provider)
        encrypted = self._cipher.encrypt(json.dumps(tokens).encode())
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(encrypted)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, provider):
        from cryptography.fernet import InvalidToken
        try:
            return json.loads(self._cipher.decrypt(self._path(provider).read_bytes()))
        except (InvalidToken, ValueError, OSError):
            raise PublishError("Cannot read encrypted credentials; authorize again or check key") from None
