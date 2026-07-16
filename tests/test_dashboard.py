"""Tests for the product dashboard endpoints: summaries, aggregate stats, delete, certs."""
import httpx
from fastapi.testclient import TestClient

from app import main
from app.database import SessionLocal
from app.models import Certificate, Company, EcfrCache, Product


def _client() -> TestClient:
    # Isolate: clear products/companies/certs/cache so each test starts clean.
    with SessionLocal() as db:
        db.query(Certificate).delete()
        db.query(Product).delete()
        db.query(Company).delete()
        db.query(EcfrCache).delete()
        db.commit()
    return TestClient(main.app)


def _new(tc, name, source=None, company=None):
    return tc.post(
        "/api/products",
        json={"name": name, "source_input": source, "company_name": company},
    ).json()


def test_list_returns_computed_summary():
    tc = _client()
    p = _new(tc, "Painted toy", source="toy for ages 2, plastic, painted", company="Acme")
    # Answer just the age question -> becomes a children's product.
    tc.post(f"/api/products/{p['id']}/answer", json={"key": "intended_age_max", "value": 2})

    rows = tc.get("/api/products").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Painted toy"
    assert row["company_name"] == "Acme"
    assert row["certificate_type"] == "CPC"
    assert row["applicable_count"] >= 1
    assert row["interview_complete"] is False
    assert row["questions_answered"] >= 1


def test_dashboard_aggregates():
    tc = _client()
    a = _new(tc, "Kids toy", source="toy for a 2 year old, plastic")
    tc.post(f"/api/products/{a['id']}/answer", json={"key": "intended_age_max", "value": 2})
    b = _new(tc, "Steel shelf")
    tc.post(f"/api/products/{b['id']}/answer", json={"key": "intended_age_max", "value": 99})

    d = tc.get("/api/dashboard").json()
    assert d["total"] == 2
    assert d["by_certificate_type"].get("CPC", 0) >= 1
    assert d["by_certificate_type"].get("GCC", 0) >= 1
    assert d["interviews_incomplete"] >= 1


def test_delete_product():
    tc = _client()
    p = _new(tc, "Temp product")
    assert tc.delete(f"/api/products/{p['id']}").json()["deleted"] == p["id"]
    assert tc.get(f"/api/products/{p['id']}").status_code == 404
    assert tc.get("/api/products").json() == []


def test_certificates_listed_after_draft():
    tc = _client()
    p = _new(tc, "Draftable", source="general use metal shelf")
    tc.post(f"/api/products/{p['id']}/answer", json={"key": "intended_age_max", "value": 99})
    # Drive remaining questions to completion, then draft.
    while not tc.get(f"/api/products/{p['id']}/next-question").json()["complete"]:
        q = tc.get(f"/api/products/{p['id']}/next-question").json()["question"]
        val = 99 if q["type"] == "int" else ("other" if q["type"] == "single" else ([] if q["type"] == "multi" else False))
        tc.post(f"/api/products/{p['id']}/answer", json={"key": q["key"], "value": val})

    tc.post(f"/api/products/{p['id']}/draft", json={})
    certs = tc.get(f"/api/products/{p['id']}/certificates").json()
    assert len(certs) == 1
    assert certs[0]["cert_type"] == "GCC"
    assert "ready_to_issue" in certs[0]

    # The draft should also show up in the product's dashboard summary count.
    row = next(r for r in tc.get("/api/products").json() if r["id"] == p["id"])
    assert row["certificate_count"] == 1
