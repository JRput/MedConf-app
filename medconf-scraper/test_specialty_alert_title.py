"""Tests for the specialty alert title label (display label, not slug)."""
from fire_specialty_alerts import _format_title
from specialty_taxonomy import parent_label


def test_title_workshops():
    assert _format_title(2, "Oncology", {"workshop"}) == "2 new Oncology workshops"


def test_title_mixed_single():
    assert _format_title(1, "Cardiology", {"conference", "course"}) == "1 new Cardiology event"


def test_parent_label():
    assert parent_label("oncology") == "Oncology"
    assert parent_label("Oncology") == "Oncology"
    assert parent_label("not-a-specialty") is None
