"""Knowledge base + the learning loop.

The knowledge base is a set of **structured rule objects** (not free text). Seed rules
ship in ``app/data/knowledge_base.json``. User-reported rules/exemptions enter through
:func:`capture_reported_rule`, which turns a free-form report into the same structured
shape and files it in a **review queue** with a verification tier — so unverified
community input can never silently become authoritative.

Verification tiers:

- ``official``            — sourced from statute / CFR / Federal Register.
- ``community_verified``  — a user report that a reviewer has approved.
- ``community_unverified``— a user report awaiting review (excluded from assessments
  unless the caller explicitly opts in).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"

VERIFICATION_TIERS = ("official", "community_verified", "community_unverified")


def load_seed_rules() -> list[dict[str, Any]]:
    """Load the shipped seed rule objects."""
    with _DATA.open() as fh:
        return json.load(fh)["rules"]


def capture_reported_rule(report: dict[str, Any]) -> dict[str, Any]:
    """Turn a user's free-form regulatory tip into a structured, reviewable rule object.

    This is the intake half of the learning loop. It never trusts the input: the result
    is always filed as ``community_unverified`` and must be approved before it counts.

    ``report`` is expected to carry whatever the capture interview collected, e.g.::

        {
          "title": "New exemption for recycled PET in toys",
          "citation": "16 CFR 1307.x",
          "summary": "...",
          "category": "chemical",
          "cert_required": "CPC",
          "applies_when": {...},      # optional structured predicate
          "source_url": "https://...",
          "reported_by": "abe@example.com"
        }
    """
    structured = {
        "id": report.get("id") or _slug(report.get("title", "user-rule")),
        "title": report.get("title", "").strip(),
        "category": report.get("category", "user-reported"),
        "citation": report.get("citation", "").strip(),
        "standard": report.get("standard", ""),
        "summary": report.get("summary", "").strip(),
        "cert_required": report.get("cert_required", "review"),
        "third_party_testing": bool(report.get("third_party_testing", False)),
        "applies_when": report.get("applies_when", False),  # False => never auto-applies until scoped
        "exemptions": report.get("exemptions", []),
        "verification_tier": "community_unverified",
        "source_url": report.get("source_url", ""),
        "reported_by": report.get("reported_by"),
        "status": "pending_review",
    }
    return structured


def missing_capture_questions(report: dict[str, Any]) -> list[dict[str, str]]:
    """Return the follow-up questions needed to make a reported rule usable.

    A tip like "there's a new lead exemption" is useless until we know its citation,
    scope, and source. This is what makes the capture feel like a consultant filing
    knowledge properly rather than a text box.
    """
    questions: list[dict[str, str]] = []
    if not report.get("citation"):
        questions.append({
            "key": "citation",
            "prompt": "What is the legal citation for this rule or exemption (CFR part, statute section, or Federal Register doc number)?",
        })
    if not report.get("summary"):
        questions.append({
            "key": "summary",
            "prompt": "In one or two sentences, what does the rule require or exempt?",
        })
    if not report.get("applies_when"):
        questions.append({
            "key": "scope",
            "prompt": "Which products does this apply to? (e.g. children's products, toys with plastic parts, apparel). This becomes the rule's scope.",
        })
    if not report.get("source_url"):
        questions.append({
            "key": "source_url",
            "prompt": "Do you have a link to the source (Federal Register, eCFR, or CPSC page) so a reviewer can verify it?",
        })
    return questions


def _slug(text: str) -> str:
    return "-".join(text.lower().split())[:60] or "user-rule"
