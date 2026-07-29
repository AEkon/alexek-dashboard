"""Session cookie auth for the dashboard.

Callers: backend/main.py middleware, GET /login, POST /api/login, POST /api/logout.
No existing auth module (Grep: only Basic Auth middleware in main.py).
No data files — env vars DASHBOARD_USERNAME/PASSWORD/SECRET only.
User: "make the login ui match. i dont want a popup"
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

COOKIE_NAME = "hq_session"
SESSION_DAYS = 30


def expected_username() -> str:
    return os.getenv("DASHBOARD_USERNAME", "admin")


def expected_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "")


def auth_configured() -> bool:
    return bool(expected_password())


def auth_required_in_env() -> bool:
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))


def _secret() -> bytes:
    raw = os.getenv("DASHBOARD_SECRET") or expected_password() or "dev-insecure"
    return hashlib.sha256(raw.encode("utf-8")).digest()


def create_session_token(username: str) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{username}:{exp}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_session_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        username, exp_s, sig = token.rsplit(":", 2)
        exp = int(exp_s)
        if exp < int(time.time()):
            return None
        payload = f"{username}:{exp_s}"
        expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected):
            return None
        return username
    except Exception:
        return None


def credentials_valid(username: str, password: str) -> bool:
    expected_user = expected_username()
    expected_pass = expected_password()
    if not expected_pass:
        return False
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(
        password, expected_pass
    )


def session_cookie_kwargs(token: str) -> dict:
    secure = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
    return {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "max_age": SESSION_DAYS * 86400,
        "path": "/",
    }
