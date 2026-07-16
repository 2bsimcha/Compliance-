"""Test-report ingestion + coverage analysis.

Turns an uploaded lab test report (PDF) into structured findings, then answers the
question that actually matters for a certificate: **does this testing cover what the
product's assessment requires?**

Pipeline:

1. :func:`extract_text` — pull text from the PDF (pypdf; text-based reports).
2. :func:`parse_report` — Claude structured-output extraction of what was tested, the
   results, the lab identity, and dates (heuristic fallback with no API key).
3. :func:`coverage` — match the report's tested standards against the rules that require
   third-party testing, producing covered / missing / failed lists. This is the gap
   analysis that tells you what's still needed before a valid CPC/GCC.

Citation matching is token-based: both the rules' citations and the report's tested
standards are reduced to normalized tokens (``16CFR1303``, ``ASTMF963``) and matched on
set overlap, so "16 CFR 1303" matches "16 CFR 1303 (lead in paint)" and "ASTM F963-23"
matches "ASTM F963".
"""
from __future__ import annotations

import io
import os
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MODEL = os.getenv("COMPLIANCE_LLM_MODEL", "claude-opus-4-8")

_CFR_RE = re.compile(r"(\d+)\s*C\.?\s*F\.?\s*R\.?\s*§?\s*(\d+)", re.I)
_ASTM_RE = re.compile(r"ASTM\s*([A-Z]\s*\d+)", re.I)


# ---------------------------------------------------------------------------
# 1. PDF text extraction
# ---------------------------------------------------------------------------
def extract_text(pdf_bytes: bytes, max_chars: int = 60000) -> str:
    """Extract text from a (text-based) PDF. Returns '' if nothing is extractable."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a bad page shouldn't kill the whole report
            continue
    return "\n".join(parts)[:max_chars].strip()


# ---------------------------------------------------------------------------
# 2. Structured parse
# ---------------------------------------------------------------------------
class TestedItem(BaseModel):
    __test__ = False  # not a pytest test class
    standard: str = Field(description="The standard/regulation tested, e.g. '16 CFR 1303' or 'ASTM F963'.")
    result: Literal["pass", "fail", "other"] = Field(description="Overall result for this standard.")
    notes: Optional[str] = Field(None, description="Any qualifier (e.g. specific sub-test, value).")


class TestReportFindings(BaseModel):
    __test__ = False  # not a pytest test class
    product_description: Optional[str] = Field(None, description="Product the report covers.")
    lab_name: Optional[str] = Field(None, description="Testing laboratory name.")
    cpsc_lab_code: Optional[str] = Field(None, description="CPSC-accepted lab code/number, if present.")
    report_date: Optional[str] = Field(None, description="Report or test date (as written).")
    tested: list[TestedItem] = Field(default_factory=list, description="Each standard tested and its result.")


_SYSTEM_PROMPT = (
    "You are a CPSC compliance assistant reading a product safety TEST REPORT from a "
    "laboratory. Extract, into the given schema, which standards/regulations were tested "
    "and the result of each (pass/fail), plus the lab name, any CPSC lab code, and the "
    "report date. Map each tested standard to its citation form where possible (e.g. "
    "'16 CFR 1303', 'ASTM F963', '16 CFR 1307'). Only include standards the report "
    "actually tested; do not infer. Leave unknown fields null."
)


def parse_report(text: str, *, use_llm: bool | None = None) -> dict[str, Any]:
    """Parse report text into structured findings (LLM when available, else heuristic)."""
    want_llm = use_llm if use_llm is not None else bool(os.getenv("ANTHROPIC_API_KEY"))
    if want_llm:
        try:
            obj = _call_llm(text)
            data = obj.model_dump()
            data["_source"] = "llm"
            return data
        except Exception as exc:  # noqa: BLE001
            data = _heuristic_parse(text)
            data["_llm_error"] = f"{type(exc).__name__}: {exc}"
            return data
    return _heuristic_parse(text)


def _call_llm(text: str) -> TestReportFindings:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_format=TestReportFindings,
    )
    return response.parsed_output


def _heuristic_parse(text: str) -> dict[str, Any]:
    """Best-effort no-LLM parse: find standard tokens and guess pass/fail nearby.

    Deliberately conservative — real structured extraction needs the LLM. This at least
    surfaces which standards the report mentions so coverage isn't empty offline.
    """
    tested: list[dict[str, Any]] = []
    seen: set[str] = set()
    low = text.lower()
    for label in _standard_labels(text):
        if label in seen:
            continue
        seen.add(label)
        # Look for pass/fail within a window after the mention.
        idx = low.find(label.lower())
        window = low[idx: idx + 120] if idx >= 0 else ""
        result = "pass" if "pass" in window else ("fail" if "fail" in window else "other")
        tested.append({"standard": label, "result": result, "notes": None})
    return {
        "product_description": None,
        "lab_name": None,
        "cpsc_lab_code": None,
        "report_date": None,
        "tested": tested,
        "_source": "heuristic",
    }


# ---------------------------------------------------------------------------
# 3. Coverage / gap analysis
# ---------------------------------------------------------------------------
def coverage(applicable_rules: list[dict[str, Any]], findings: dict[str, Any]) -> dict[str, Any]:
    """Compare a report's tested standards against the rules that require lab testing.

    ``applicable_rules`` is the list from ``rules.assess(...)["applicable_rules"]``.
    Returns which required tests are covered (with the matching result), which are still
    missing, and any covered-but-FAILED tests (a failing report doesn't satisfy a rule).
    """
    tested = findings.get("tested", [])
    tested_index: list[tuple[set[str], dict[str, Any]]] = [
        (_tokens(t.get("standard", "")), t) for t in tested
    ]

    required = [
        r for r in applicable_rules
        if r.get("third_party_testing") and not r.get("exemptions_met")
    ]

    covered, missing, failed = [], [], []
    for rule in required:
        rule_tokens = _tokens(rule.get("citation", ""))
        match = next((t for toks, t in tested_index if rule_tokens & toks), None)
        if match is None:
            missing.append({"id": rule["id"], "title": rule["title"], "citation": rule["citation"]})
        elif match.get("result") == "fail":
            failed.append({
                "id": rule["id"], "title": rule["title"], "citation": rule["citation"],
                "result": "fail", "tested_as": match.get("standard"),
            })
        else:
            covered.append({
                "id": rule["id"], "title": rule["title"], "citation": rule["citation"],
                "result": match.get("result"), "tested_as": match.get("standard"),
            })

    return {
        "required_count": len(required),
        "covered": covered,
        "missing": missing,
        "failed": failed,
        "fully_covered": not missing and not failed and bool(required),
    }


def _tokens(text: str) -> set[str]:
    """Normalize a citation/standard string to matchable tokens (CFR part, ASTM number)."""
    out: set[str] = set()
    for title, part in _CFR_RE.findall(text or ""):
        out.add(f"{title}CFR{part}".upper())
    for astm in _ASTM_RE.findall(text or ""):
        out.add(("ASTM" + astm.replace(" ", "")).upper())
    return out


def _standard_labels(text: str) -> list[str]:
    """Human-readable standard labels found in text (for the heuristic parser)."""
    labels: list[str] = []
    for title, part in _CFR_RE.findall(text or ""):
        labels.append(f"{title} CFR {part}")
    for astm in _ASTM_RE.findall(text or ""):
        labels.append("ASTM " + astm.replace(" ", ""))
    return labels
