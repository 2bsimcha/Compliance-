from app.engine import drafter, knowledge, rules


def test_cpc_draft_lists_labs_and_gap_analysis():
    attrs = {
        "is_childrens_product": True,
        "intended_age_max": 2,
        "product_category": "toy",
        "materials": ["plastic"],
        "has_paint_or_coating": True,
        "has_small_parts": True,
    }
    result = rules.assess(attrs, knowledge.load_seed_rules())
    out = drafter.draft_certificate({"name": "Stacking rings"}, result)
    assert out["draft"]["certificate_type"] == "CPC"
    assert "third_party_labs" in out["draft"]
    # Missing party info + required lab testing => not ready to issue.
    assert out["gap_analysis"]["ready_to_issue"] is False
    assert any("lab" in g.lower() for g in out["gap_analysis"]["outstanding"])


def test_gcc_draft_has_all_required_elements():
    attrs = {"is_childrens_product": False, "product_category": "furniture", "materials": ["metal"]}
    result = rules.assess(attrs, knowledge.load_seed_rules())
    out = drafter.draft_certificate({"name": "Steel shelf"}, result)
    d = out["draft"]
    assert d["certificate_type"] == "GCC"
    for field in ("product_identification", "certifier", "records_contact", "manufacture", "testing"):
        assert field in d


def test_learning_loop_quarantines_user_input():
    captured = knowledge.capture_reported_rule({"title": "New phthalate exemption"})
    assert captured["verification_tier"] == "community_unverified"
    assert captured["status"] == "pending_review"
    # Un-scoped tips never auto-apply.
    assert captured["applies_when"] is False


def test_capture_asks_the_right_follow_ups():
    qs = knowledge.missing_capture_questions({"title": "Something"})
    keys = {q["key"] for q in qs}
    assert {"citation", "summary", "scope", "source_url"} <= keys
