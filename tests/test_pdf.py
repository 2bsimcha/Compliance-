"""Tests for certificate PDF rendering and the download endpoint."""
import httpx
from fastapi.testclient import TestClient

from app import main
from app.database import SessionLocal
from app.engine import drafter, knowledge, pdf, rules
from app.models import Certificate, Product


def _draft_for(attrs):
    result = rules.assess(attrs, knowledge.load_seed_rules())
    return drafter.draft_certificate({"name": "Test product"}, result)


def test_render_produces_valid_pdf_bytes():
    out = _draft_for({"is_childrens_product": False, "product_category": "furniture", "materials": ["metal"]})
    data = pdf.render_certificate_pdf(out["draft"], out["gap_analysis"])
    assert isinstance(data, bytes)
    assert data.startswith(b"%PDF")  # PDF magic header
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 800


def test_cpc_pdf_mentions_labs_and_regulations():
    attrs = {
        "is_childrens_product": True, "intended_age_max": 2, "product_category": "toy",
        "materials": ["plastic"], "has_paint_or_coating": True, "has_small_parts": True,
    }
    out = _draft_for(attrs)
    data = pdf.render_certificate_pdf(out["draft"], out["gap_analysis"], compress=False)
    # Uncompressed stream: text is present verbatim in the content bytes.
    text = data.decode("latin-1", errors="ignore")
    assert "Children's Product Certificate" in text
    assert "1303" in text  # lead-in-paint citation appears


def test_filename_slug():
    assert pdf.filename_for("Wooden Stacking Rings!", "CPC") == "CPC-Wooden-Stacking-Rings.pdf"
    assert pdf.filename_for("", "GCC") == "GCC-certificate.pdf"


def test_pdf_download_endpoint():
    with SessionLocal() as db:
        db.query(Certificate).delete()
        db.query(Product).delete()
        db.commit()
    tc = TestClient(main.app)
    p = tc.post("/api/products", json={"name": "Steel shelf", "source_input": "general use steel shelf"}).json()
    tc.post(f"/api/products/{p['id']}/answer", json={"key": "intended_age_max", "value": 99})
    tc.post(f"/api/products/{p['id']}/draft", json={})
    cert = tc.get(f"/api/products/{p['id']}/certificates").json()[0]

    r = tc.get(f"/api/products/{p['id']}/certificates/{cert['id']}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "Steel-shelf" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")


def test_pdf_download_404_for_wrong_product():
    tc = TestClient(main.app)
    assert tc.get("/api/products/999999/certificates/1/pdf").status_code == 404
