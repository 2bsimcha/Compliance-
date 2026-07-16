"""Applicability engine.

Given a product's attributes, decide:

- which certificate is required (GCC vs CPC),
- which rules apply (with citations),
- which exemptions are available (with citations),
- what third-party lab testing is triggered.

All matching is done with the shared predicate DSL so the logic stays consistent with
the interview.
"""
from __future__ import annotations

from typing import Any, Iterable

from .predicates import evaluate, is_satisfied


def assess(attrs: dict[str, Any], rules: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Run the applicability assessment for a product.

    Returns a structured result: applicable rules (with any met exemptions attached),
    the recommended certificate type, testing obligations, and a list of open questions
    whose answers would change the outcome.
    """
    applicable: list[dict[str, Any]] = []
    undecided: list[dict[str, Any]] = []

    for rule in rules:
        verdict = evaluate(rule.get("applies_when"), attrs)
        if verdict is True:
            applicable.append(_with_exemptions(rule, attrs))
        elif verdict is None:
            undecided.append({"id": rule["id"], "title": rule["title"]})

    cert_type = _certificate_type(attrs, applicable)
    testing = _testing_obligations(applicable)

    return {
        "certificate_type": cert_type,
        "is_childrens_product": attrs.get("is_childrens_product"),
        "applicable_rules": applicable,
        "third_party_testing_required": testing["required"],
        "testing_rules": testing["rules"],
        "undecided_rules": undecided,
        "ready_for_assessment": attrs.get("is_childrens_product") is not None,
    }


def _with_exemptions(rule: dict[str, Any], attrs: dict[str, Any]) -> dict[str, Any]:
    """Attach any exemptions the product qualifies for to an applicable rule."""
    met = []
    for ex in rule.get("exemptions", []):
        if is_satisfied(ex.get("applies_when"), attrs):
            met.append({
                "id": ex["id"],
                "citation": ex["citation"],
                "summary": ex["summary"],
            })
    return {
        "id": rule["id"],
        "title": rule["title"],
        "category": rule.get("category"),
        "citation": rule["citation"],
        "standard": rule.get("standard"),
        "summary": rule["summary"],
        "cert_required": rule.get("cert_required"),
        "third_party_testing": rule.get("third_party_testing", False),
        "verification_tier": rule.get("verification_tier", "official"),
        "source_url": rule.get("source_url"),
        "exemptions_met": met,
        # An exemption may remove the testing obligation while the rule still applies.
        "testing_exempt": bool(met) and bool(rule.get("third_party_testing")),
    }


def _certificate_type(attrs: dict[str, Any], applicable: list[dict[str, Any]]) -> str:
    """Decide the certificate the product needs.

    - Children's product -> CPC (Children's Product Certificate).
    - Otherwise, if any general-use rule applies -> GCC (General Certificate of Conformity).
    - If nothing applies and it's a general product -> GCC still commonly advisable.
    """
    if attrs.get("is_childrens_product") is True:
        return "CPC"
    if attrs.get("is_childrens_product") is False:
        return "GCC"
    return "undetermined"


def _testing_obligations(applicable: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect which applicable rules require third-party lab testing (net of exemptions)."""
    testing_rules = []
    for r in applicable:
        if r["third_party_testing"] and not r["exemptions_met"]:
            testing_rules.append({"id": r["id"], "title": r["title"], "citation": r["citation"]})
    return {"required": bool(testing_rules), "rules": testing_rules}
