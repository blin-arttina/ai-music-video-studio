"""
Blind Art Server auth client.

Every Blind Art app authenticates against the central Blind Art Server
instead of keeping its own user table. This mirrors the client already
used by BuildYourAppAI: same endpoints, same generous timeout (Render's
free tier can cold-start slowly), same cached-token pattern.

Usage:
    from source.project.auth_client import BlindArtAuthClient
    auth = BlindArtAuthClient()
    token = auth.login(email, password)
    user = auth.me(token)
"""

import json
import time
from pathlib import Path

import requests

from config import get_config

CONFIG = get_config()

TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "configuration" / ".auth_cache.json"


class BlindArtAuthError(Exception):
    """Raised when the Blind Art Server rejects or cannot process a request."""


class BlindArtAuthClient:
    def __init__(self, base_url: str = None, timeout: int = None):
        self.base_url = (base_url or CONFIG.BLIND_ART_SERVER_URL).rstrip("/")
        self.timeout = timeout or CONFIG.BLIND_ART_SERVER_TIMEOUT

    # ---- core HTTP calls -------------------------------------------------

    def signup(self, email: str, password: str, name: str = "") -> dict:
        return self._post("/auth/signup", {"email": email, "password": password, "name": name})

    def login(self, email: str, password: str) -> str:
        """Returns a JWT access token."""
        data = self._post("/auth/login", {"email": email, "password": password})
        token = data.get("access_token") or data.get("token")
        if not token:
            raise BlindArtAuthError("Blind Art Server did not return a token.")
        return token

    def me(self, token: str) -> dict:
        return self._get("/auth/me", token)

    # ---- cached-token convenience (used for service accounts, e.g. this
    # app connecting to Blind Art Server as itself for shared operations) --

    def login_cached(self, email: str, password: str, force: bool = False) -> str:
        if not force and TOKEN_CACHE_PATH.exists():
            try:
                cached = json.loads(TOKEN_CACHE_PATH.read_text())
                if cached.get("email") == email and cached.get("token"):
                    return cached["token"]
            except (json.JSONDecodeError, OSError):
                pass

        token = self.login(email, password)
        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_PATH.write_text(
            json.dumps({"email": email, "token": token, "cached_at": time.time()})
        )
        return token

    # ---- internals ---------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise BlindArtAuthError(f"Could not reach Blind Art Server: {exc}") from exc
        return self._handle(resp)

    def _get(self, path: str, token: str) -> dict:
        try:
            resp = requests.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise BlindArtAuthError(f"Could not reach Blind Art Server: {exc}") from exc
        return self._handle(resp)

    @staticmethod
    def _handle(resp: "requests.Response") -> dict:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error") or resp.json().get("message")
            except ValueError:
                detail = resp.text
            raise BlindArtAuthError(f"Blind Art Server error ({resp.status_code}): {detail}")
        try:
            return resp.json()
        except ValueError:
            return {}
