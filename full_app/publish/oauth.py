"""Explicit OAuth authorization and refresh; no implicit browser or server."""
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

from .common import PublishError, expect, json_body, request


class OAuth:
    def __init__(self, provider, client_id, client_secret, redirect_uri, store, client):
        if provider not in ("youtube", "tiktok"):
            raise ValueError("Unknown provider")
        self.provider, self.client_id = provider, client_id
        self._secret, self.redirect_uri = client_secret, redirect_uri
        self.store, self.client = store, client
        self._pending = None

    def authorization_url(self):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        self._pending = (state, verifier, time.time())
        args = dict(response_type="code", redirect_uri=self.redirect_uri, state=state)
        if self.provider == "youtube":
            endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
            args.update(client_id=self.client_id, scope="https://www.googleapis.com/auth/youtube.upload",
                        access_type="offline", prompt="consent", code_challenge_method="S256",
                        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))
        else:
            endpoint = "https://www.tiktok.com/v2/auth/authorize/"
            args.update(client_key=self.client_id, scope="video.upload")
        return endpoint + "?" + urlencode(args)

    def exchange(self, code, state):
        pending, self._pending = self._pending, None
        if (not pending or not isinstance(state, str) or not secrets.compare_digest(state, pending[0])
                or time.time() - pending[2] > 600 or not code):
            raise PublishError("Invalid or expired OAuth state")
        args = dict(grant_type="authorization_code", code=code, redirect_uri=self.redirect_uri)
        if self.provider == "youtube":
            args["code_verifier"] = pending[1]
        self._token_request(args)

    def _token_request(self, args, previous=None):
        google = self.provider == "youtube"
        endpoint = "https://oauth2.googleapis.com/token" if google else "https://open.tiktokapis.com/v2/oauth/token/"
        args.update({"client_id" if google else "client_key": self.client_id, "client_secret": self._secret})
        data = json_body(expect(request(self.client, "POST", endpoint, data=args), {200}))
        if data.get("error") or not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise PublishError("OAuth token request failed")
        try:
            expiry = float(data["expires_in"])
            if not 0 < expiry < 1e9:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise PublishError("Invalid OAuth expiry") from None
        tokens = {**(previous or {}), **data, "expires_at": time.time() + expiry}
        self.store.save(self.provider, tokens)

    def access_token(self):
        tokens = self.store.load(self.provider)
        if tokens.get("expires_at", 0) <= time.time() + 60:
            if not tokens.get("refresh_token"):
                raise PublishError("OAuth authorization required")
            self._token_request(dict(grant_type="refresh_token", refresh_token=tokens["refresh_token"]), tokens)
            tokens = self.store.load(self.provider)
        return tokens["access_token"]
