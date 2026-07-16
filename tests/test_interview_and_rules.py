from app.engine import interview, knowledge, rules


def _run_interview(answers):
    """Drive the interview by feeding answers keyed by question until complete."""
    attrs = {}
    guard = 0
    while (q := interview.next_question(attrs)) is not None and guard < 50:
        guard += 1
        key = q["key"]
        assert key in answers, f"test needs an answer for surfaced question {key!r}"
        interview.apply_answer(attrs, key, answers[key])
    return attrs


def test_childrens_toy_triggers_cpc_and_testing():
    attrs = _run_interview({
        "intended_age_max": 2,
        "product_category": "toy",
        "materials": ["plastic"],
        "has_paint_or_coating": True,
        "has_small_parts": True,
        "has_button_batteries": False,
        "has_loose_magnets": False,
        "is_sleep_related": False,
    })
    assert attrs["is_childrens_product"] is True

    result = rules.assess(attrs, knowledge.load_seed_rules())
    assert result["certificate_type"] == "CPC"
    assert result["third_party_testing_required"] is True

    ids = {r["id"] for r in result["applicable_rules"]}
    # Core children's-product rules should all fire for a painted plastic toy < 3 yrs.
    assert {"lead-content-substrate", "lead-in-paint", "phthalates", "astm-f963-toy-safety", "small-parts", "tracking-label"} <= ids


def test_general_product_gets_gcc_no_childrens_rules():
    attrs = _run_interview({
        "intended_age_max": 99,          # general-use product
        "product_category": "electronics",
        "materials": ["metal", "electronic_components"],
        "has_button_batteries": False,
    })
    assert attrs["is_childrens_product"] is False
    result = rules.assess(attrs, knowledge.load_seed_rules())
    assert result["certificate_type"] == "GCC"
    ids = {r["id"] for r in result["applicable_rules"]}
    assert "lead-content-substrate" not in ids  # children's-only rule must not apply


def test_natural_material_exemption_removes_lead_testing():
    attrs = _run_interview({
        "intended_age_max": 5,
        "product_category": "other",
        "materials": ["untreated_wood", "natural_fiber"],
        "has_paint_or_coating": False,
        "has_loose_magnets": False,
    })
    result = rules.assess(attrs, knowledge.load_seed_rules())
    lead = next(r for r in result["applicable_rules"] if r["id"] == "lead-content-substrate")
    assert lead["exemptions_met"], "untreated natural materials should meet the 1500.91 lead exemption"
    # That rule should no longer be in the mandatory testing list.
    assert all(t["id"] != "lead-content-substrate" for t in result["testing_rules"])


def test_button_battery_rule_applies_to_general_product():
    attrs = _run_interview({
        "intended_age_max": 99,
        "product_category": "electronics",
        "materials": ["electronic_components"],
        "has_button_batteries": True,
    })
    result = rules.assess(attrs, knowledge.load_seed_rules())
    ids = {r["id"] for r in result["applicable_rules"]}
    assert "button-battery-reeses-law" in ids
