"""Endpoint + cache tests for the eCFR API surface, using a mock-transport client."""
import httpx
from fastapi.testclient import TestClient

from app import main
from app.database import SessionLocal
from app.engine.ecfr import ECFRClient
from app.models import EcfrCache
from tests.test_ecfr import _handler


def _make_client(handler=_handler) -> TestClient:
    # The temp DB is shared across tests; clear the eCFR cache so each test starts clean.
    with SessionLocal() as db:
        db.query(EcfrCache).delete()
        db.commit()
    main.ecfr_client = ECFRClient(transport=httpx.MockTransport(handler))
    return TestClient(main.app)


def test_currency_endpoint_and_cache():
    tc = _make_client()
    r1 = tc.get("/api/ecfr/currency")
    assert r1.status_code == 200
    assert r1.json()["up_to_date_as_of"] == "2026-07-10"
    assert r1.json().get("_cached") is not True  # first call is live

    r2 = tc.get("/api/ecfr/currency")
    assert r2.json().get("_cached") is True  # second call served from cache


def test_section_endpoint():
    tc = _make_client()
    r = tc.get("/api/ecfr/section", params={"citation": "16 CFR 1303.1"})
    body = r.json()
    assert body["ok"] is True
    assert "90 ppm" in body["text"]


def test_section_endpoint_rejects_non_cfr_citation():
    tc = _make_client()
    r = tc.get("/api/ecfr/section", params={"citation": "ASTM F963"})
    assert r.json()["ok"] is False


def test_refresh_knowledge_endpoint():
    tc = _make_client()
    r = tc.post("/api/knowledge/refresh")
    body = r.json()
    assert body["refreshed"] >= 10
    # CFR-based rules resolve; statute-only ones (tracking label) don't.
    assert body["resolved"] >= 1
    assert body["unresolved"] >= 1


def test_failure_not_cached():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked", request=request)

    tc = _make_client(boom)
    r = tc.get("/api/ecfr/currency")
    assert r.json()["ok"] is False
    assert r.json().get("_cached") is not True  # failures must not be pinned in cache
