"""Adaptive interview engine.

This is the consultant. Instead of a static form, it serves the *next relevant*
question given what is already known about the product, branching on prior answers via
the shared predicate DSL. Every question carries a ``reason`` — the "why am I asking
this" that a good human consultant always gives — and the citation it maps to.

A question is offered only when:

- its ``when`` predicate is satisfied by the answers so far, AND
- it has not already been answered.

Answers are stored as a flat ``attrs`` dict, which is exactly what the rules engine
consumes — so finishing the interview *is* having a complete assessment input.
"""
from __future__ import annotations

from typing import Any

from .predicates import evaluate, is_satisfied

# Question types the UI understands: "bool", "int", "single" (choices), "multi" (choices).
QUESTIONS: list[dict[str, Any]] = [
    {
        "key": "intended_age_max",
        "type": "int",
        "prompt": "What is the maximum age (in years) of the child this product is designed or intended for? Enter 99 if it is a general-use product not intended for children.",
        "reason": "Whether a product is a 'children's product' (intended for children 12 or under) is the single biggest fork in CPSC compliance — it decides GCC vs CPC and whether third-party lab testing is required.",
        "citation": "16 CFR 1200 (definition of children's product); CPSIA sec. 3(a)(2)",
        "when": True,
        "derives": {
            "is_childrens_product": lambda v: v is not None and v <= 12,
        },
    },
    {
        "key": "product_category",
        "type": "single",
        "choices": ["toy", "apparel", "furniture", "jewelry", "electronics", "child_care_article", "other"],
        "prompt": "Which category best describes the product?",
        "reason": "Category selects which product-specific safety standards can apply (e.g. ASTM F963 for toys, 16 CFR 1610 flammability for apparel).",
        "citation": "Varies by category",
        "when": True,
        "derives": {
            "is_child_care_article": lambda v: v == "child_care_article",
        },
    },
    {
        "key": "materials",
        "type": "multi",
        "choices": ["plastic", "metal", "untreated_wood", "treated_wood", "natural_fiber", "synthetic_fabric", "glass", "electronic_components", "other"],
        "prompt": "Which materials are used in the accessible parts of the product? (select all that apply)",
        "reason": "Materials drive chemical testing (lead, phthalates) and available exemptions — e.g. untreated natural materials are exempt from lead testing under 16 CFR 1500.91.",
        "citation": "16 CFR 1500.91 (material exemptions)",
        "when": True,
    },
    {
        "key": "has_paint_or_coating",
        "type": "bool",
        "prompt": "Does the product have any paint, ink, or surface coating on it?",
        "reason": "Surface coatings on children's products trigger the 90 ppm lead-in-paint limit (16 CFR 1303), which is separate from the substrate lead limit.",
        "citation": "16 CFR 1303",
        "when": {"attr": "is_childrens_product", "op": "eq", "value": True},
    },
    {
        "key": "has_small_parts",
        "type": "bool",
        "prompt": "Does the product contain, or can it release, any small parts (parts that could fit in a small-parts test cylinder ~ a toilet-paper tube)?",
        "reason": "For products intended for children under 3, small parts are a regulated choking hazard under 16 CFR 1501.",
        "citation": "16 CFR 1501",
        "when": {"all": [
            {"attr": "is_childrens_product", "op": "eq", "value": True},
            {"attr": "intended_age_max", "op": "lte", "value": 3}
        ]},
    },
    {
        "key": "has_button_batteries",
        "type": "bool",
        "prompt": "Does the product contain button or coin cell batteries?",
        "reason": "Button/coin cell batteries trigger Reese's Law (16 CFR 1263): secure compartments and warning labeling, regardless of whether it's a children's product.",
        "citation": "16 CFR 1263; Reese's Law",
        "when": {"any": [
            {"attr": "product_category", "op": "eq", "value": "toy"},
            {"attr": "product_category", "op": "eq", "value": "electronics"},
            {"attr": "materials", "op": "contains", "value": "electronic_components"}
        ]},
    },
    {
        "key": "has_loose_magnets",
        "type": "bool",
        "prompt": "Does the product contain loose or separable magnets small enough to be swallowed?",
        "reason": "Loose high-powered magnets are regulated by flux-index limits under 16 CFR 1262.",
        "citation": "16 CFR 1262",
        "when": {"any": [
            {"attr": "product_category", "op": "eq", "value": "toy"},
            {"attr": "product_category", "op": "eq", "value": "other"}
        ]},
    },
    {
        "key": "is_sleep_related",
        "type": "bool",
        "prompt": "Is the product intended to provide sleeping accommodations for an infant (e.g. crib, bassinet, sleeper, inclined sleeper)?",
        "reason": "Infant sleep products must meet the applicable durable infant/toddler product standard (16 CFR 1236 and related).",
        "citation": "16 CFR 1236",
        "when": {"all": [
            {"attr": "is_childrens_product", "op": "eq", "value": True},
            {"attr": "intended_age_max", "op": "lte", "value": 3}
        ]},
    },
    {
        "key": "is_sleepwear",
        "type": "bool",
        "prompt": "Is the product children's sleepwear (sizes 0-14)?",
        "reason": "Children's sleepwear must be flame-resistant or meet the snug-fit exemption (16 CFR 1615/1616).",
        "citation": "16 CFR 1615; 16 CFR 1616",
        "when": {"all": [
            {"attr": "is_childrens_product", "op": "eq", "value": True},
            {"attr": "product_category", "op": "eq", "value": "apparel"}
        ]},
    },
    {
        "key": "is_snug_fit",
        "type": "bool",
        "prompt": "Is the sleepwear tight-fitting ('snug-fit') within the specified maximum dimensions?",
        "reason": "Snug-fit sleepwear is exempt from the flame-resistance requirement but must carry the required warning hangtag.",
        "citation": "16 CFR 1615.1(o) / 1616.2(m)",
        "when": {"attr": "is_sleepwear", "op": "eq", "value": True},
    },
]

_BY_KEY = {q["key"]: q for q in QUESTIONS}


def next_question(attrs: dict[str, Any]) -> dict[str, Any] | None:
    """Return the next relevant, unanswered question — or None when the interview is done."""
    for q in QUESTIONS:
        if q["key"] in attrs:
            continue
        if is_satisfied(q["when"], attrs):
            return _public(q)
    return None


def apply_answer(attrs: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Record an answer and run any derived attributes (e.g. is_childrens_product).

    Returns the updated attrs dict (mutated in place and returned for convenience).
    """
    q = _BY_KEY.get(key)
    if q is None:
        raise KeyError(f"Unknown question key: {key!r}")
    attrs[key] = value
    for derived_key, fn in q.get("derives", {}).items():
        attrs[derived_key] = fn(value)
    return attrs


def progress(attrs: dict[str, Any]) -> dict[str, int]:
    """How many relevant questions have been answered vs. currently outstanding."""
    answered = sum(1 for q in QUESTIONS if q["key"] in attrs)
    relevant = sum(1 for q in QUESTIONS if q["key"] in attrs or is_satisfied(q["when"], attrs))
    return {"answered": answered, "relevant": relevant}


def _public(q: dict[str, Any]) -> dict[str, Any]:
    """Strip non-serializable internals (predicates/lambdas) before sending to the client."""
    return {
        "key": q["key"],
        "type": q["type"],
        "prompt": q["prompt"],
        "reason": q["reason"],
        "citation": q["citation"],
        "choices": q.get("choices"),
    }
