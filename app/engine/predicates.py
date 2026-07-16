"""Shared predicate DSL.

A single, tiny boolean-expression evaluator is used in two places:

- The **interview** engine uses predicates as each question's ``when`` guard, so a
  question is only asked when it is relevant to the product built up so far.
- The **rules** engine uses predicates as each rule's ``applies_when`` / exemption
  guard, so applicability is computed from the same product attributes.

Keeping one evaluator means the interview and the compliance logic can never drift
apart: if the rules care about an attribute, the interview knows to ask for it.

Predicate grammar (JSON-friendly dicts)::

    {"attr": "is_childrens_product", "op": "eq", "value": true}
    {"attr": "intended_age_max", "op": "lte", "value": 12}
    {"attr": "materials", "op": "contains", "value": "metal"}
    {"all": [<pred>, <pred>, ...]}      # logical AND
    {"any": [<pred>, <pred>, ...]}      # logical OR
    {"not": <pred>}                     # negation
    True                                # always matches (unconditional)

Unknown / not-yet-answered attributes evaluate to ``None`` and cause the leaf to be
"unsatisfied but not disqualifying" — see :func:`evaluate` for the tri-state details.
"""
from __future__ import annotations

from typing import Any, Mapping

_MISSING = object()


def _leaf(pred: Mapping[str, Any], attrs: Mapping[str, Any]) -> bool | None:
    """Evaluate a single comparison leaf.

    Returns ``None`` when the attribute has not been answered yet, so callers can
    distinguish "known false" from "unknown".
    """
    attr = pred["attr"]
    op = pred.get("op", "eq")
    expected = pred.get("value")
    actual = attrs.get(attr, _MISSING)

    if actual is _MISSING or actual is None:
        return None

    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "lte":
        return actual is not None and actual <= expected
    if op == "gte":
        return actual is not None and actual >= expected
    if op == "lt":
        return actual is not None and actual < expected
    if op == "gt":
        return actual is not None and actual > expected
    if op == "contains":
        try:
            return expected in actual
        except TypeError:
            return False
    if op == "in":
        try:
            return actual in expected
        except TypeError:
            return False
    if op == "truthy":
        return bool(actual)
    raise ValueError(f"Unknown predicate op: {op!r}")


def evaluate(pred: Any, attrs: Mapping[str, Any]) -> bool | None:
    """Evaluate a predicate against product attributes.

    Tri-state result:

    - ``True``  — the predicate is satisfied.
    - ``False`` — the predicate is contradicted by known attributes.
    - ``None``  — the predicate cannot be decided yet (depends on an unanswered
      attribute). The interview uses this to know a question is still "pending".
    """
    if pred is True or pred is None:
        return True
    if pred is False:
        return False

    if "all" in pred:
        results = [evaluate(p, attrs) for p in pred["all"]]
        if any(r is False for r in results):
            return False
        if any(r is None for r in results):
            return None
        return True

    if "any" in pred:
        results = [evaluate(p, attrs) for p in pred["any"]]
        if any(r is True for r in results):
            return True
        if any(r is None for r in results):
            return None
        return False

    if "not" in pred:
        inner = evaluate(pred["not"], attrs)
        if inner is None:
            return None
        return not inner

    return _leaf(pred, attrs)


def is_satisfied(pred: Any, attrs: Mapping[str, Any]) -> bool:
    """True only when the predicate is *definitely* satisfied (``None`` counts as no)."""
    return evaluate(pred, attrs) is True
