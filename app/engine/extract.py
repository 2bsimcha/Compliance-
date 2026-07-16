"""Intake extraction.

Pre-fills product attributes from an unstructured input — a pasted product description,
a URL's page text, or a test report — so the interview starts with a head-start instead
of a blank slate.

Two backends:

- **LLM (Claude), preferred** — used when ``ANTHROPIC_API_KEY`` is set. Calls the
  Anthropic Messages API with a **structured-output schema** (`messages.parse` +
  Pydantic), so the model fills a validated object rather than emitting free text. The
  model reads the description/report the way a consultant would and maps it to the
  controlled vocabulary the rules engine understands.
- **Heuristic fallback** — transparent keyword matching, used when no API key is set or
  the API call fails. Keeps the whole app runnable offline with zero configuration.

Design guarantees:

- **Never authoritative on the critical fork.** Extraction returns the child-age as a
  *hint* (``intended_age_max_hint``), never the authoritative ``intended_age_max`` — the
  consultant interview still asks and confirms the single biggest CPSC fork
  (children's product vs general-use). Everything else it fills is a head-start the
  interview will skip if already known.
- **Never blocks intake.** Any LLM failure falls back to heuristics; the error is
  attached as ``_llm_error`` for visibility, not raised.
"""
from __future__ import annotations

import os
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Default model is the mandated Opus tier; override with COMPLIANCE_LLM_MODEL to trade
# cost for capability (e.g. claude-haiku-4-5 for cheap, high-volume extraction).
MODEL = os.getenv("COMPLIANCE_LLM_MODEL", "claude-opus-4-8")

# Controlled vocabularies — must match the interview/rules engine keys exactly.
Category = Literal["toy", "apparel", "furniture", "jewelry", "electronics", "child_care_article", "other"]
Material = Literal[
    "plastic", "metal", "untreated_wood", "treated_wood",
    "natural_fiber", "synthetic_fabric", "glass", "electronic_components", "other",
]


class ExtractedAttributes(BaseModel):
    """The structured shape the model must fill. Every field optional — the model leaves
    a field null when the text doesn't clearly support a value (no guessing)."""

    product_category: Optional[Category] = Field(
        None, description="Best single category for the product."
    )
    materials: Optional[list[Material]] = Field(
        None, description="Materials present in accessible parts; only those clearly indicated."
    )
    has_paint_or_coating: Optional[bool] = Field(
        None, description="True if the product has paint, ink, printing, or a surface coating."
    )
    has_small_parts: Optional[bool] = Field(
        None, description="True if the product has or can release small detachable parts."
    )
    has_button_batteries: Optional[bool] = Field(
        None, description="True if it contains button or coin cell batteries."
    )
    has_loose_magnets: Optional[bool] = Field(
        None, description="True if it contains loose/separable magnets small enough to swallow."
    )
    is_sleep_related: Optional[bool] = Field(
        None, description="True if it is an infant sleep product (crib, bassinet, sleeper)."
    )
    is_sleepwear: Optional[bool] = Field(
        None, description="True if it is children's sleepwear."
    )
    intended_age_max: Optional[int] = Field(
        None,
        description="Best estimate of the max intended child age in years; use 99 for a "
        "general-use product not intended for children. This is a HINT only.",
    )
    rationale: Optional[str] = Field(
        None, description="One sentence on what in the text drove these values."
    )


_SYSTEM_PROMPT = (
    "You are a CPSC compliance intake assistant. Read the provided product description, "
    "web page text, or test report and extract objective product attributes into the "
    "given schema. Rules: (1) Only fill a field when the text clearly supports it; leave "
    "anything uncertain as null — do not guess. (2) Map to the provided controlled "
    "vocabularies exactly. (3) The age field is a best-estimate hint that a human will "
    "confirm; still provide your best read (99 for a clearly general-use/adult product). "
    "(4) Consider material and construction cues that matter for CPSC (paint/coating, "
    "small parts, button/coin batteries, loose magnets, infant sleep, sleepwear)."
)


def extract_attributes(text: str, *, use_llm: bool | None = None) -> dict[str, Any]:
    """Extract product attributes from unstructured text.

    Uses the LLM backend when available (``ANTHROPIC_API_KEY`` set), otherwise heuristics.
    ``use_llm`` overrides that decision (used in tests). Never raises — LLM failures fall
    back to heuristics with the error recorded in ``_llm_error``.
    """
    want_llm = use_llm if use_llm is not None else bool(os.getenv("ANTHROPIC_API_KEY"))
    if not want_llm:
        return _heuristic_extract(text)
    try:
        return llm_extract(text)
    except Exception as exc:  # noqa: BLE001 - intake must never fail on extraction
        fallback = _heuristic_extract(text)
        fallback["_llm_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


# ---------------------------------------------------------------------------
# LLM backend
# ---------------------------------------------------------------------------
def llm_extract(text: str) -> dict[str, Any]:
    """Claude-backed structured extraction. Requires ``ANTHROPIC_API_KEY``."""
    obj = _call_llm(text)
    attrs = _result_to_attrs(obj)
    attrs["_source"] = "llm"
    attrs["_model"] = MODEL
    return attrs


def _call_llm(text: str) -> ExtractedAttributes:
    import anthropic  # imported lazily so the app runs without the SDK installed

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_format=ExtractedAttributes,
    )
    return response.parsed_output


def _result_to_attrs(obj: ExtractedAttributes) -> dict[str, Any]:
    """Map the validated model output to engine attribute keys.

    Pure function (no network) so it is fully unit-testable. Drops nulls, renames the
    age to a non-authoritative hint, and mirrors the interview's derived attributes.
    """
    attrs: dict[str, Any] = {"_confidence": "model"}
    data = obj.model_dump(exclude_none=True)

    # Age stays a HINT — the consultant interview still confirms the critical fork.
    if "intended_age_max" in data:
        attrs["intended_age_max_hint"] = data.pop("intended_age_max")

    rationale = data.pop("rationale", None)
    if rationale:
        attrs["_rationale"] = rationale

    attrs.update(data)

    # Mirror the interview's derived attribute so downstream rules stay consistent.
    if attrs.get("product_category") == "child_care_article":
        attrs["is_child_care_article"] = True

    return attrs


# ---------------------------------------------------------------------------
# Heuristic fallback (offline, zero-config)
# ---------------------------------------------------------------------------
_MATERIAL_HINTS = {
    "plastic": "plastic", "vinyl": "plastic", "pvc": "plastic",
    "metal": "metal", "steel": "metal", "aluminum": "metal", "brass": "metal",
    "wood": "untreated_wood",
    "cotton": "natural_fiber", "wool": "natural_fiber",
    "polyester": "synthetic_fabric", "nylon": "synthetic_fabric",
    "glass": "glass",
    "battery": "electronic_components", "led": "electronic_components",
}

_CATEGORY_HINTS = {
    "toy": "toy", "plush": "toy", "doll": "toy",
    "shirt": "apparel", "pajama": "apparel", "clothing": "apparel", "apparel": "apparel",
    "crib": "child_care_article", "stroller": "child_care_article",
    "necklace": "jewelry", "bracelet": "jewelry",
    "earbuds": "electronics", "charger": "electronics",
}

_AGE_RE = re.compile(r"(\d+)\s*(?:-|to|\+)?\s*(\d+)?\s*(?:year|yr|month|mo)", re.I)


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
    if "magnet" in low:
        suggested["has_loose_magnets"] = True
    if any(w in low for w in ("button cell", "coin cell", "cr2032", "button battery")):
        suggested["has_button_batteries"] = True

    m = _AGE_RE.search(low)
    if m:
        ages = [int(g) for g in m.groups() if g]
        if ages:
            suggested["intended_age_max_hint"] = max(ages)

    if suggested.get("product_category") == "child_care_article":
        suggested["is_child_care_article"] = True

    return suggested
