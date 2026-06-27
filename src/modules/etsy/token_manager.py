"""
Etsy OAuth 2.0 PKCE Token Manager (Step 8.1)

Handles:
- PKCE authorization URL generation
- Authorization code exchange
- Token persistence (encrypted with Fernet)
- Auto-refresh before expiry
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import structlog
from cryptography.fernet import Fernet

_log = structlog.get_logger(__name__)

ETSY_AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

_DATA_DIR = Path("./data")
_TOKEN_FILE = _DATA_DIR / "etsy_token.json"
_KEY_FILE = _DATA_DIR / "etsy_encryption.key"
_PKCE_FILE = _DATA_DIR / "etsy_pkce_state.json"

ETSY_SCOPES = "listings_w listings_r listings_d shops_r transactions_r"


class TokenManager:
    def __init__(self, api_key: str, redirect_uri: str) -> None:
        self._api_key = api_key
        self._redirect_uri = redirect_uri
        self._token_data: dict | None = None
        self._fernet = self._init_fernet()

    # ── Encryption ─────────────────────────────────────────────────────────────

    @staticmethod
    def _init_fernet() -> Fernet:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        if _KEY_FILE.exists():
            return Fernet(_KEY_FILE.read_bytes())
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
        _log.info("Generated new Etsy encryption key", path=str(_KEY_FILE))
        return Fernet(key)

    def _save_token(self, data: dict) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        encrypted = self._fernet.encrypt(json.dumps(data).encode())
        _TOKEN_FILE.write_bytes(encrypted)

    def _load_token(self) -> dict | None:
        if not _TOKEN_FILE.exists():
            return None
        try:
            return json.loads(self._fernet.decrypt(_TOKEN_FILE.read_bytes()))
        except Exception as exc:
            _log.warning("Failed to decrypt token file", error=str(exc))
            return None

    # ── PKCE helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def get_auth_url(self) -> str:
        """Build PKCE authorization URL and persist state for the callback."""
        code_verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(16)

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _PKCE_FILE.write_text(
            json.dumps({"code_verifier": code_verifier, "state": state})
        )

        params = {
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": ETSY_SCOPES,
            "client_id": self._api_key,
            "state": state,
            "code_challenge": self._make_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{ETSY_AUTHORIZE_URL}?{urlencode(params)}"

    # ── Code exchange ──────────────────────────────────────────────────────────

    async def exchange_code(self, code: str, state: str) -> bool:
        """Exchange authorization code for access + refresh token."""
        if not _PKCE_FILE.exists():
            _log.error("PKCE state file missing — cannot exchange code")
            return False

        pkce = json.loads(_PKCE_FILE.read_text())
        if pkce.get("state") != state:
            _log.error("OAuth state mismatch", expected=pkce.get("state"), got=state)
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                ETSY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self._api_key,
                    "redirect_uri": self._redirect_uri,
                    "code": code,
                    "code_verifier": pkce["code_verifier"],
                },
            )
            resp.raise_for_status()
            token_data = resp.json()

        token_data["obtained_at"] = time.time()
        self._save_token(token_data)
        self._token_data = token_data
        _PKCE_FILE.unlink(missing_ok=True)
        _log.info("Etsy OAuth token obtained and saved")
        return True

    # ── Token refresh ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_expired(data: dict) -> bool:
        obtained_at = data.get("obtained_at", 0)
        expires_in = data.get("expires_in", 3600)
        return time.time() > obtained_at + expires_in - 300  # 5-min buffer

    async def _refresh(self, data: dict) -> dict | None:
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            _log.error("No refresh_token in stored data")
            return None
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                ETSY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._api_key,
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            new_data = resp.json()
        new_data["obtained_at"] = time.time()
        self._save_token(new_data)
        _log.info("Etsy token refreshed successfully")
        return new_data

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._token_data is None:
            self._token_data = self._load_token()

        if self._token_data is None:
            raise RuntimeError(
                "No Etsy token found. Please connect via /admin/etsy/connect"
            )

        if self._is_expired(self._token_data):
            refreshed = await self._refresh(self._token_data)
            if refreshed is None:
                raise RuntimeError(
                    "Token expired and refresh failed. Please reconnect via /admin/etsy/connect"
                )
            self._token_data = refreshed

        return self._token_data["access_token"]

    def is_connected(self) -> bool:
        if self._token_data is None:
            self._token_data = self._load_token()
        return self._token_data is not None

    def disconnect(self) -> None:
        self._token_data = None
        _TOKEN_FILE.unlink(missing_ok=True)
        _log.info("Etsy token removed")
