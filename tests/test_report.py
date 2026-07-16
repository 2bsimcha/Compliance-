"""Tests for test-report ingestion: PDF extraction, parsing, coverage, and the API."""
from fpdf import FPDF
from fastapi.testclient import TestClient

from app import main
from app.database import SessionLocal
from app.engine import knowledge, report, rules
from app.engine.report import TestReportFindings, TestedItem, coverage
from app.models import Product, TestReport


def _report_pdf(lines: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in lines:
        pdf.multi_cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


CHILD_TOY = {
    "is_childrens_product": True, "intended_age_max": 2, "product_category": "toy",
    "materials": ["plastic"], "has_paint_or_coating": True, "has_small_parts": True,
}


def _applicable():
    return rules.assess(CHILD_TOY, knowledge.load_seed_rules())["applicable_rules"]


# -- token matching + coverage ----------------------------------------------
def test_tokens_extraction():
    assert report._tokens("16 CFR 1303 (lead in paint)") == {"16CFR1303"}
    assert "ASTMF963" in report._tokens("16 CFR 1250; ASTM F963")
    assert report._tokens("ASTM F963-23") == {"ASTMF963"}


def test_coverage_partial():
    findings = {"tested": [
        {"standard": "16 CFR 1303", "result": "pass"},
        {"standard": "ASTM F963-23", "result": "pass"},
        {"standard": "16 CFR 1500.87", "result": "pass"},
    ]}
    cov = coverage(_applicable(), findings)
    assert cov["required_count"] == 5           # lead, lead-paint, phthalates, F963, small parts
    assert len(cov["covered"]) == 3
    missing_ids = {m["id"] for m in cov["missing"]}
    assert missing_ids == {"phthalates", "small-parts"}
    assert cov["fully_covered"] is False


def test_coverage_flags_failed_test():
    findings = {"tested": [{"standard": "16 CFR 1303", "result": "fail"}]}
    cov = coverage(_applicable(), findings)
    assert cov["failed"] and cov["failed"][0]["id"] == "lead-in-paint"
    # A failing test does not count as covered.
    assert all(c["id"] != "lead-in-paint" for c in cov["covered"])


def test_coverage_full():
    findings = {"tested": [
        {"standard": s, "result": "pass"}
        for s in ["16 CFR 1500.87", "16 CFR 1303", "16 CFR 1307", "ASTM F963", "16 CFR 1501"]
    ]}
    cov = coverage(_applicable(), findings)
    assert cov["fully_covered"] is True
    assert not cov["missing"] and not cov["failed"]


# -- PDF extraction + parsing -----------------------------------------------
def test_extract_text_from_pdf():
    data = _report_pdf(["Lab: Acme Testing", "16 CFR 1303 PASS", "ASTM F963 PASS"])
    text = report.extract_text(data)
    assert "1303" in text and "F963" in text


def test_heuristic_parse_finds_standards_and_results():
    text = "Tested to 16 CFR 1303 - PASS. ASTM F963 result: FAIL."
    parsed = report.parse_report(text, use_llm=False)
    assert parsed["_source"] == "heuristic"
    by_std = {t["standard"]: t["result"] for t in parsed["tested"]}
    assert by_std["16 CFR 1303"] == "pass"
    assert by_std["ASTM F963"] == "fail"


def test_llm_parse_mocked(monkeypatch):
    def fake(text):
        return TestReportFindings(
            lab_name="Acme Lab", report_date="2026-01-05",
            tested=[TestedItem(standard="16 CFR 1303", result="pass")],
        )

    monkeypatch.setattr(report, "_call_llm", fake)
    parsed = report.parse_report("...", use_llm=True)
    assert parsed["_source"] == "llm"
    assert parsed["lab_name"] == "Acme Lab"
    assert parsed["tested"][0]["standard"] == "16 CFR 1303"


# -- endpoint ----------------------------------------------------------------
def test_upload_and_coverage_endpoint():
    with SessionLocal() as db:
        db.query(TestReport).delete()
        db.query(Product).delete()
        db.commit()
    tc = TestClient(main.app)
    p = tc.post("/api/products", json={
        "name": "Painted toy", "source_input": "painted plastic toy for ages 2 years",
    }).json()
    tc.post(f"/api/products/{p['id']}/answer", json={"key": "intended_age_max", "value": 2})

    pdf_bytes = _report_pdf([
        "Acme Test Labs", "16 CFR 1500.87: PASS", "16 CFR 1303: PASS",
        "16 CFR 1307: PASS", "ASTM F963: PASS", "16 CFR 1501: PASS",
    ])
    r = tc.post(
        f"/api/products/{p['id']}/test-reports",
        files={"file": ("lab-report.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "lab-report.pdf"
    assert body["coverage"]["fully_covered"] is True

    # Listed, then deletable.
    assert len(tc.get(f"/api/products/{p['id']}/test-reports").json()) == 1
    rid = body["id"]
    assert tc.delete(f"/api/products/{p['id']}/test-reports/{rid}").json()["deleted"] == rid
    assert tc.get(f"/api/products/{p['id']}/test-reports").json() == []
