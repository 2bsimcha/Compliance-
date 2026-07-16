"""Offline tests for the eCFR integration using an injected mock transport.

No live network is required (and the eCFR host is often egress-blocked in CI): we stub
the eCFR API with canned JSON/XML that mirrors the real response shapes.
"""
import httpx
import pytest

from app.engine.ecfr import ECFRClient, parse_citation

TITLES_JSON = {
    "titles": [
        {
            "number": 16,
            "name": "Commercial Practices",
            "up_to_date_as_of": "2026-07-10",
            "latest_amended_on": "2026-06-30",
            "latest_issue_date": "2026-07-10",
            "reserved": False,
        }
    ]
}

SECTION_XML = """<?xml version="1.0"?>
<ECFR>
  <DIV5 TYPE="PART" N="1303">
    <HEAD>PART 1303—BAN OF LEAD-CONTAINING PAINT</HEAD>
    <DIV8 TYPE="SECTION" N="1303.1">
      <HEAD>&#167; 1303.1 Scope and application.</HEAD>
      <P>(a) In this part, the Commission declares that lead-containing paint is a banned hazardous product.</P>
      <P>(b) The limit is 0.009 percent (90 ppm).</P>
    </DIV8>
  </DIV5>
</ECFR>"""

SEARCH_JSON = {
    "meta": {"total_count": 2},
    "results": [
        {
            "hierarchy_headings": {"section": "§ 1303.1"},
            "headings": {"section": "Scope and application"},
            "full_text_excerpt": "lead-containing paint is a banned hazardous product",
            "hierarchy": {"part": "1303", "section": "1303.1"},
            "url": "https://www.ecfr.gov/current/title-16/part-1303/section-1303.1",
        }
    ],
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/titles.json"):
        return httpx.Response(200, json=TITLES_JSON)
    if "/full/" in path:
        return httpx.Response(200, text=SECTION_XML, headers={"content-type": "application/xml"})
    if "/search/v1/results" in path:
        return httpx.Response(200, json=SEARCH_JSON)
    return httpx.Response(404, text="not found")


@pytest.fixture
def client():
    c = ECFRClient(transport=httpx.MockTransport(_handler))
    yield c
    c.close()


# -- citation parsing --------------------------------------------------------
@pytest.mark.parametrize(
    "citation,part,section",
    [
        ("16 CFR 1303", "1303", None),
        ("16 CFR 1500.87", "1500", "1500.87"),
        ("15 U.S.C. 1278a; 16 CFR 1500.87", "1500", "1500.87"),
        ("16 C.F.R. § 1610", "1610", None),
    ],
)
def test_parse_citation(citation, part, section):
    ref = parse_citation(citation)
    assert ref is not None
    assert ref.part == part
    assert ref.section == section
    assert ref.title == 16


def test_parse_citation_statute_only_returns_none():
    assert parse_citation("15 U.S.C. 2063(a)(5)") is None
    assert parse_citation("ASTM F963") is None


# -- live-ish calls via mock -------------------------------------------------
def test_title_currency(client):
    info = client.title_currency(16)
    assert info["ok"] is True
    assert info["up_to_date_as_of"] == "2026-07-10"
    assert info["name"] == "Commercial Practices"


def test_section_text_flattens_xml(client):
    ref = parse_citation("16 CFR 1303.1")
    result = client.section_text(ref)
    assert result["ok"] is True
    assert result["current_as_of"] == "2026-07-10"
    assert "90 ppm" in result["text"]
    assert "1303.1" in result["heading"]
    assert result["source_url"].endswith("section-1303.1")


def test_search(client):
    out = client.search("lead in paint")
    assert out["ok"] is True
    assert out["total"] == 2
    assert out["results"][0]["part"] == "1303"


def test_refresh_rule_resolved(client):
    rule = {"id": "lead-in-paint", "citation": "16 CFR 1303"}
    status = client.refresh_rule(rule)
    assert status["resolved"] is True
    assert status["current_as_of"] == "2026-07-10"
    assert status["excerpt"]


def test_refresh_rule_unresolved_for_statute(client):
    rule = {"id": "tracking-label", "citation": "15 U.S.C. 2063(a)(5)"}
    status = client.refresh_rule(rule)
    assert status["resolved"] is False
    assert "statute" in status["reason"].lower() or "no cfr" in status["reason"].lower()


# -- graceful degradation ----------------------------------------------------
def test_network_failure_is_graceful():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked by egress policy", request=request)

    c = ECFRClient(transport=httpx.MockTransport(boom))
    info = c.title_currency(16)
    assert info["ok"] is False
    assert "unreachable" in info["error"].lower()
    # section lookup should also fail softly, not raise
    ref = parse_citation("16 CFR 1303")
    assert c.section_text(ref)["ok"] is False
    c.close()
