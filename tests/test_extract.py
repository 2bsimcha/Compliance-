"""Tests for intake extraction — pure mapping, heuristic fallback, and the LLM path
with the Anthropic call mocked (no network / API key needed)."""
from app.engine import extract
from app.engine.extract import ExtractedAttributes, _result_to_attrs


# -- pure mapping ------------------------------------------------------------
def test_result_to_attrs_maps_and_renames_age():
    obj = ExtractedAttributes(
        product_category="toy",
        materials=["plastic", "metal"],
        has_paint_or_coating=True,
        intended_age_max=2,
        rationale="Plush painted toy for a toddler.",
    )
    attrs = _result_to_attrs(obj)
    # Age must become a non-authoritative HINT, never the authoritative key.
    assert attrs["intended_age_max_hint"] == 2
    assert "intended_age_max" not in attrs
    assert attrs["product_category"] == "toy"
    assert attrs["materials"] == ["plastic", "metal"]
    assert attrs["has_paint_or_coating"] is True
    assert attrs["_rationale"].startswith("Plush")
    assert attrs["_confidence"] == "model"


def test_result_to_attrs_drops_nulls_and_derives_child_care():
    obj = ExtractedAttributes(product_category="child_care_article")
    attrs = _result_to_attrs(obj)
    assert attrs["is_child_care_article"] is True
    # Unset fields must not appear.
    assert "has_small_parts" not in attrs
    assert "materials" not in attrs


# -- heuristic fallback ------------------------------------------------------
def test_heuristic_path_when_llm_disabled():
    attrs = extract.extract_attributes(
        "Plush dinosaur toy for ages 3 years, polyester fabric, printed eyes, contains button cell battery",
        use_llm=False,
    )
    assert attrs["_source"] == "heuristic"
    assert attrs["product_category"] == "toy"
    assert "synthetic_fabric" in attrs["materials"]
    assert attrs["has_paint_or_coating"] is True
    assert attrs["has_button_batteries"] is True
    assert attrs["intended_age_max_hint"] == 3


# -- LLM path (mocked) -------------------------------------------------------
def test_llm_path_success(monkeypatch):
    def fake_call(text):
        assert "shelf" in text
        return ExtractedAttributes(product_category="furniture", materials=["metal"], intended_age_max=99)

    monkeypatch.setattr(extract, "_call_llm", fake_call)
    attrs = extract.extract_attributes("A steel garage shelf", use_llm=True)
    assert attrs["_source"] == "llm"
    assert attrs["product_category"] == "furniture"
    assert attrs["intended_age_max_hint"] == 99
    assert "_model" in attrs


def test_llm_failure_falls_back_to_heuristic(monkeypatch):
    def boom(text):
        raise RuntimeError("API unreachable")

    monkeypatch.setattr(extract, "_call_llm", boom)
    attrs = extract.extract_attributes("cotton baby pajama set", use_llm=True)
    # Falls back to heuristics, records the error, never raises.
    assert attrs["_source"] == "heuristic"
    assert "API unreachable" in attrs["_llm_error"]
    assert attrs["product_category"] == "apparel"
