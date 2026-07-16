"""Intake extraction.

Pre-fills product attributes from an unstructured input — a pasted product description,
a URL's page text, or a test report — so the interview starts with a head-start instead
of a blank slate.

The MVP uses transparent keyword heuristics so it runs with **no API key**. The seam for
a real LLM extractor (Claude with a structured tool-call schema) is
:func:`llm_extract`, wired in only when ``ANTHROPIC_API_KEY`` is set. This keeps the
scaffold runnable offline while making the upgrade path obvious.
"""
from __future__ import annotations

import os
import re
from typing import Any

# Keyword -> attribute hints. Deliberately conservative: extraction only *suggests*
# attributes; the interview still confirms everything that matters.
_MATERIAL_HINTS = {
    "plastic": "plastic",
    "vinyl": "plastic",
    "pvc": "plastic",
    "metal": "metal",
    "steel": "metal",
    "aluminum": "metal",
    "brass": "metal",
    "wood": "untreated_wood",
    "cotton": "natural_fiber",
    "wool": "natural_fiber",
    "polyester": "synthetic_fabric",
    "nylon": "synthetic_fabric",
    "glass": "glass",
    "battery": "electronic_components",
    "led": "electronic_components",
}

_CATEGORY_HINTS = {
    "toy": "toy",
    "plush": "toy",
    "doll": "toy",
    "shirt": "apparel",
    "pajama": "apparel",
    "clothing": "apparel",
    "apparel": "apparel",
    "crib": "child_care_article",
    "stroller": "child_care_article",
    "necklace": "jewelry",
    "bracelet": "jewelry",
    "earbuds": "electronics",
    "charger": "electronics",
}

_AGE_RE = re.compile(r"(\d+)\s*(?:-|to|\+)?\s*(\d+)?\s*(?:year|yr|month|mo)", re.I)


def extract_attributes(text: str) -> dict[str, Any]:
    """Heuristic (or LLM, if configured) extraction of product attributes from text."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return llm_extract(text)
        except Exception:
            # Never let extraction failure block intake — fall back to heuristics.
            pass
    return _heuristic_extract(text)


def _heuristic_extract(text: str) -> dict[str, Any]:
    low = text.lower()
    suggested: dict[str, Any] = {"_source": "heuristic", "_confidence": "low"}

    materials = sorted({v for k, v in _MATERIAL_HINTS.items() if k in low})
    if materials:
        suggested["materials"] = materials

    for k, v in _CATEGORY_HINTS.items():
        if k in low:
            suggested["product_category"] = v
            break

    if any(w in low for w in ("paint", "painted", "coated", "coating", "printed", "ink")):
        suggested["has_paint_or_coating"] = True
    if any(w in low for w in ("magnet",)):
        suggested["has_loose_magnets"] = True
    if any(w in low for w in ("button cell", "coin cell", "cr2032", "button battery")):
        suggested["has_button_batteries"] = True

    m = _AGE_RE.search(low)
    if m:
        ages = [int(g) for g in m.groups() if g]
        if ages:
            suggested["intended_age_max_hint"] = max(ages)

    return suggested


def llm_extract(text: str) -> dict[str, Any]:  # pragma: no cover - requires API key
    """LLM-backed extraction (Claude, structured tool-call). Wired only when configured.

    Kept as a thin seam so the MVP runs offline. A production implementation would call
    the Anthropic Messages API forcing a tool with the product-attribute schema, so the
    model fills a validated structure rather than emitting free text.
    """
    raise NotImplementedError(
        "LLM extraction not enabled in the MVP. Set ANTHROPIC_API_KEY and implement the "
        "structured tool-call here to upgrade from heuristics."
    )
