"""Tests for the single-gate auth. Auth is off by default (no APP_PASSWORD); these
enable it by monkeypatching the module globals the middleware reads at call time."""
import pytest
from fastapi.testclient import TestClient

from app import auth, main


@pytest.fixture
def authed_env(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "APP_USERNAME", "admin")
    monkeypatch.setattr(auth, "APP_PASSWORD", "s3cret")
    yield


def test_healthz_public_and_reports_auth(authed_env):
    tc = TestClient(main.app)
    r = tc.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "auth": True}


def test_api_blocked_without_session(authed_env):
    tc = TestClient(main.app)
    r = tc.get("/api/products")
    assert r.status_code == 401


def test_page_redirects_to_login(authed_env):
    tc = TestClient(main.app)
    r = tc.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_flow_grants_access_then_logout_revokes(authed_env):
    tc = TestClient(main.app)

    # Wrong password → 401, no access.
    bad = tc.post("/login", data={"username": "admin", "password": "nope"}, follow_redirects=False)
    assert bad.status_code == 401
    assert tc.get("/api/products").status_code == 401

    # Correct credentials → session cookie set; API now reachable.
    ok = tc.post("/login", data={"username": "admin", "password": "s3cret"}, follow_redirects=False)
    assert ok.status_code == 303
    assert tc.get("/api/products").status_code == 200

    # Logout clears the session.
    tc.get("/logout", follow_redirects=False)
    assert tc.get("/api/products").status_code == 401


def test_static_login_page_public(authed_env):
    tc = TestClient(main.app)
    r = tc.get("/login")
    assert r.status_code == 200
    assert "Sign in" in r.text


def test_auth_disabled_lets_everything_through(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    tc = TestClient(main.app)
    assert tc.get("/api/products").status_code == 200
    assert tc.get("/healthz").json()["auth"] is False
