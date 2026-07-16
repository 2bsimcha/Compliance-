"""Live eCFR (Electronic Code of Federal Regulations) integration.

Talks to the official, free eCFR API at https://www.ecfr.gov to:

- report how **current** Title 16 (where CPSC's rules live) is,
- fetch the **live text** of a CFR section given a citation,
- **full-text search** the CFR, and
- **refresh** a knowledge-base rule against its live source so citations never go stale.

Design notes
------------
- The HTTP client is injectable (``transport=``) so the whole module is testable
  offline with ``httpx.MockTransport`` — no live network needed for tests.
- Every network call **degrades gracefully**: on any failure it returns a structured
  ``{"ok": False, "error": ...}`` result instead of raising, so a blocked host or an
  eCFR outage never breaks the core compliance flow (assessments don't depend on it).
- Responses are cached by the caller (see ``models.EcfrCache``) to avoid hammering eCFR.

eCFR API reference: https://www.ecfr.gov/developers/documentation/api/v1
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://www.ecfr.gov"
DEFAULT_TITLE = 16  # Commercial Practices — CPSC is Chapter II of Title 16.
_UA = {"User-Agent": "cpsc-compliance-consultant/0.1 (+compliance MVP)"}

# Matches CFR references like "16 CFR 1303", "16 CFR 1500.87", "16 C.F.R. 1610".
_CFR_RE = re.compile(r"(\d+)\s*C\.?\s*F\.?\s*R\.?\s*§?\s*(\d+)(?:\.(\d+))?", re.I)


@dataclass
class CfrRef:
    title: int
    part: str
    section: str | None  # full dotted number, e.g. "1500.87", or None for part-level

    @property
    def label(self) -> str:
        return f"{self.title} CFR {self.section or self.part}"

    @property
    def source_url(self) -> str:
        base = f"https://www.ecfr.gov/current/title-{self.title}/part-{self.part}"
        return f"{base}/section-{self.section}" if self.section else base


def parse_citation(citation: str) -> CfrRef | None:
    """Extract the first CFR reference from a citation string.

    Returns None for citations with no CFR component (e.g. a bare "15 U.S.C. 2063"
    statute cite or an "ASTM F963" standard), which simply aren't eCFR-resolvable.
    """
    if not citation:
        return None
    for m in _CFR_RE.finditer(citation):
        title, part, sub = m.group(1), m.group(2), m.group(3)
        section = f"{part}.{sub}" if sub else None
        return CfrRef(title=int(title), part=part, section=section)
    return None


def _verify() -> str | bool:
    """Resolve the CA bundle to trust (the agent proxy re-terminates TLS)."""
    for env in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        p = os.getenv(env)
        if p and os.path.exists(p):
            return p
    if os.path.exists("/root/.ccr/ca-bundle.crt"):
        return "/root/.ccr/ca-bundle.crt"
    return True


class ECFRClient:
    """Thin, resilient client over the eCFR REST API."""

    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        self._client = httpx.Client(
            base_url=BASE_URL,
            transport=transport,
            timeout=timeout,
            headers=_UA,
            verify=_verify(),
            trust_env=True,  # honor HTTPS_PROXY / NO_PROXY from the environment
            follow_redirects=True,
        )
        self._title_currency: dict[int, dict[str, Any]] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ECFRClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level ---------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp

    # -- currency ----------------------------------------------------------
    def title_currency(self, title: int = DEFAULT_TITLE) -> dict[str, Any]:
        """How up to date a title is. Returns the date eCFR content is current as of.

        Result: ``{"ok": True, "title": 16, "name": ..., "up_to_date_as_of": "YYYY-MM-DD",
        "latest_amended_on": ..., "reserved": bool}`` or ``{"ok": False, "error": ...}``.
        """
        try:
            data = self._get("/api/versioner/v1/titles.json").json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "error": _err(exc)}
        for t in data.get("titles", []):
            if t.get("number") == title:
                info = {
                    "ok": True,
                    "title": title,
                    "name": t.get("name"),
                    "up_to_date_as_of": t.get("up_to_date_as_of"),
                    "latest_amended_on": t.get("latest_amended_on"),
                    "latest_issue_date": t.get("latest_issue_date"),
                    "reserved": t.get("reserved", False),
                }
                self._title_currency[title] = info
                return info
        return {"ok": False, "error": f"Title {title} not found in eCFR titles index"}

    def _effective_date(self, title: int) -> str | None:
        """Pick a valid date for the versioner endpoints (they require a real date)."""
        info = self._title_currency.get(title) or self.title_currency(title)
        if not info.get("ok"):
            return None
        return info.get("up_to_date_as_of") or info.get("latest_issue_date")

    # -- section text ------------------------------------------------------
    def section_text(self, ref: CfrRef, max_chars: int = 6000) -> dict[str, Any]:
        """Fetch and flatten the live text of a CFR section (or part).

        Uses the versioner ``full`` XML endpoint restricted to the requested
        part/section, then extracts human-readable text.
        """
        date = self._effective_date(ref.title)
        if date is None:
            return {"ok": False, "error": "Could not determine a current date for the title"}

        params: dict[str, Any] = {"part": ref.part}
        if ref.section:
            params["section"] = ref.section
        try:
            resp = self._get(f"/api/versioner/v1/full/{date}/title-{ref.title}.xml", params=params)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": _err(exc), "citation": ref.label}

        heading, text = _xml_to_text(resp.text)
        truncated = len(text) > max_chars
        return {
            "ok": True,
            "citation": ref.label,
            "title": ref.title,
            "part": ref.part,
            "section": ref.section,
            "current_as_of": date,
            "heading": heading,
            "text": text[:max_chars],
            "truncated": truncated,
            "source_url": ref.source_url,
        }

    # -- search ------------------------------------------------------------
    def search(self, query: str, per_page: int = 5, title: int | None = DEFAULT_TITLE) -> dict[str, Any]:
        """Full-text search the CFR, optionally scoped to a title."""
        params: dict[str, Any] = {"query": query, "per_page": per_page}
        if title is not None:
            params["hierarchy[title]"] = str(title)
        try:
            data = self._get("/api/search/v1/results", params=params).json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "error": _err(exc)}
        results = [
            {
                "citation": r.get("hierarchy_headings", {}).get("section")
                or r.get("full_text_excerpt", "")[:80],
                "heading": r.get("headings", {}).get("section") or r.get("headings", {}).get("part"),
                "excerpt": r.get("full_text_excerpt"),
                "part": r.get("hierarchy", {}).get("part"),
                "section": r.get("hierarchy", {}).get("section"),
                "url": r.get("url"),
            }
            for r in data.get("results", [])
        ]
        return {
            "ok": True,
            "query": query,
            "total": data.get("meta", {}).get("total_count"),
            "results": results,
        }

    # -- rule refresh ------------------------------------------------------
    def refresh_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        """Refresh one knowledge-base rule against its live eCFR source.

        Returns a status record: whether the citation resolves to the CFR, the date the
        text is current as of, and a live-text excerpt for reviewer verification.
        """
        ref = parse_citation(rule.get("citation", ""))
        if ref is None:
            return {
                "rule_id": rule.get("id"),
                "citation": rule.get("citation"),
                "resolved": False,
                "reason": "No CFR reference in citation (statute-only or standard reference — not eCFR-resolvable).",
            }
        result = self.section_text(ref)
        if not result.get("ok"):
            return {
                "rule_id": rule.get("id"),
                "citation": rule.get("citation"),
                "resolved": False,
                "reason": result.get("error"),
            }
        return {
            "rule_id": rule.get("id"),
            "citation": rule.get("citation"),
            "resolved": True,
            "current_as_of": result["current_as_of"],
            "heading": result["heading"],
            "excerpt": result["text"][:600],
            "source_url": result["source_url"],
        }


# ---------------------------------------------------------------------------
# XML flattening
# ---------------------------------------------------------------------------
def _xml_to_text(xml: str) -> tuple[str | None, str]:
    """Flatten eCFR full-text XML into (heading, body-text).

    The eCFR XML nests sections in ``<DIVn>`` elements with a ``<HEAD>`` and ``<P>``
    paragraphs. We take the first HEAD as the heading and join all readable text,
    which is robust to the exact division depth returned for a subset.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None, _collapse(xml)

    # Prefer the most specific (section-level) heading over the enclosing part heading.
    # NB: an ElementTree element with no children is falsy, so test for None explicitly.
    head_el = root.find(".//*[@TYPE='SECTION']/HEAD")
    if head_el is None:
        head_el = root.find(".//HEAD")
    heading = _collapse("".join(head_el.itertext())) if head_el is not None else None

    parts: list[str] = []
    for p in root.iter():
        if p.tag in ("P", "FP", "HEAD"):
            txt = _collapse("".join(p.itertext()))
            if txt:
                parts.append(txt)
    body = "\n".join(parts) if parts else _collapse("".join(root.itertext()))
    return heading, body


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _err(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"eCFR returned HTTP {exc.response.status_code}"
    if isinstance(exc, (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout)):
        return "eCFR host unreachable (network/egress policy). Live lookups unavailable in this environment."
    return f"{type(exc).__name__}: {exc}"
