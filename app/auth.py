"""Simple single-gate authentication.

Protects the whole instance behind one shared password (set via ``APP_PASSWORD``).
This matches the app's current single-tenant design — it keeps the public out, without
pretending to be per-customer isolation (that comes with real multi-tenant accounts
later). Session state is a signed cookie via Starlette's ``SessionMiddleware``.

Behavior:

- If ``APP_PASSWORD`` is **set**, auth is enforced: unauthenticated page loads redirect
  to ``/login``; unauthenticated ``/api/*`` calls get a 401.
- If ``APP_PASSWORD`` is **unset**, auth is disabled (local-dev convenience). A warning
  is logged, and the deploy config requires the variable so production is never open by
  accident.
"""
from __future__ import annotations

import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

logger = logging.getLogger("compliance.auth")

APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD")
AUTH_ENABLED = bool(APP_PASSWORD)

# A stable secret keeps sessions valid across restarts; a random one is fine for local
# dev (sessions just reset on restart). Production sets SESSION_SECRET explicitly.
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)

# Mark the session cookie Secure (HTTPS-only) in production. Default off so local
# http:// dev still works; set SESSION_HTTPS_ONLY=true when deployed behind HTTPS.
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "").lower() in ("1", "true", "yes")

# Paths reachable without a session.
_PUBLIC_PATHS = {"/login", "/logout", "/healthz"}
_PUBLIC_PREFIXES = ("/static/",)

if not AUTH_ENABLED:
    logger.warning(
        "APP_PASSWORD is not set — authentication is DISABLED. Set APP_PASSWORD before "
        "exposing this instance publicly."
    )


def check_credentials(username: str, password: str) -> bool:
    """Constant-time credential check against the configured username/password."""
    if not AUTH_ENABLED:
        return True
    user_ok = secrets.compare_digest(username or "", APP_USERNAME)
    pass_ok = secrets.compare_digest(password or "", APP_PASSWORD or "")
    return user_ok and pass_ok


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate every request behind a session, except public paths."""

    async def dispatch(self, request: Request, call_next):
        if not AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        if request.session.get("authed"):
            return await call_next(request)

        # Unauthenticated: 401 for API (the frontend redirects), redirect for pages.
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
