"""Detail-vs-shell precedence in AgentLoop._merge_shell_and_detail."""
from llm_agent import AgentLoop

_merge = AgentLoop._merge_shell_and_detail
SHELL = {"title": "Some Congress 2027", "booking_url": "https://x.org/e/1"}


def m(shell_extra=None, detail=None):
    return _merge(None, {**SHELL, **(shell_extra or {})}, detail or {})


def test_is_sold_out_from_detail():
    assert m(detail={"is_sold_out": True})["is_sold_out"] is True


def test_is_sold_out_detail_false_beats_shell_true():
    assert m({"is_sold_out": True}, {"is_sold_out": False})["is_sold_out"] is False


def test_is_sold_out_shell_fallback_and_default():
    assert m({"is_sold_out": True})["is_sold_out"] is True
    assert m()["is_sold_out"] is False


def test_cpd_points_precedence():
    assert m({"cpd_points": 5})["cpd_points"] == 5
    assert m({"cpd_points": 5}, {"cpd_points": 0})["cpd_points"] == 0
    assert m({"cpd_points": 5}, {"cpd_points": 3})["cpd_points"] == 3


def test_is_on_demand_precedence():
    assert m({"is_on_demand": True})["is_on_demand"] is True
    assert m({"is_on_demand": True}, {"is_on_demand": False})["is_on_demand"] is False
    assert m(detail={"is_on_demand": True})["is_on_demand"] is True
