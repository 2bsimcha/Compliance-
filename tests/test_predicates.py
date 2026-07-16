from app.engine.predicates import evaluate, is_satisfied


def test_leaf_ops():
    attrs = {"is_childrens_product": True, "intended_age_max": 3, "materials": ["plastic", "metal"]}
    assert evaluate({"attr": "is_childrens_product", "op": "eq", "value": True}, attrs) is True
    assert evaluate({"attr": "intended_age_max", "op": "lte", "value": 3}, attrs) is True
    assert evaluate({"attr": "intended_age_max", "op": "gt", "value": 3}, attrs) is False
    assert evaluate({"attr": "materials", "op": "contains", "value": "plastic"}, attrs) is True
    assert evaluate({"attr": "materials", "op": "contains", "value": "wood"}, attrs) is False


def test_unknown_attr_is_none():
    assert evaluate({"attr": "missing", "op": "eq", "value": True}, {}) is None


def test_and_or_not_tristate():
    attrs = {"a": True}
    # AND with an unknown -> None (pending), not False
    assert evaluate({"all": [{"attr": "a", "op": "eq", "value": True}, {"attr": "b", "op": "eq", "value": True}]}, attrs) is None
    # AND with a known false -> False regardless of unknowns
    assert evaluate({"all": [{"attr": "a", "op": "eq", "value": False}, {"attr": "b", "op": "eq", "value": True}]}, attrs) is False
    # OR short-circuits to True on a known true
    assert evaluate({"any": [{"attr": "a", "op": "eq", "value": True}, {"attr": "b", "op": "eq", "value": True}]}, attrs) is True
    assert evaluate({"not": {"attr": "a", "op": "eq", "value": True}}, attrs) is False


def test_is_satisfied_treats_none_as_no():
    assert is_satisfied({"attr": "b", "op": "eq", "value": True}, {}) is False
    assert is_satisfied(True, {}) is True
