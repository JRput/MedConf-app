"""event_format fallback for the Tribe Events family (sources 46-49)."""
from extractors.tribe_events import TribeEventsExtractor, infer_format_from_text
from extractors.baets import BaetsExtractor


def _shell(html, **kw):
    s = {"title": "X Masterclass 2027", "categories": ["Masterclasses"], "description_html": html,
         "venue_name": None, "city": None, "is_virtual": None, "virtual_url": None,
         "cost_raw": "", "cost_details": {}}
    s.update(kw)
    return s


def _run(cls, shell):
    return cls.__new__(cls).extract_detail(None, shell, lambda p: None)


def test_baets_named_institution_is_in_person():
    html = "<h3>Royal College of Surgeons of Edinburgh</h3><p>Places are limited to 25 delegates.</p>"
    assert _run(BaetsExtractor, _shell(html)).get("event_format") == "in_person"


def test_online_wording_is_online():
    html = "<p>Join our free webinar on thyroid surgery.</p>"
    assert _run(BaetsExtractor, _shell(html)).get("event_format") == "online"


def test_no_signal_stays_unset():
    assert "event_format" not in _run(BaetsExtractor, _shell("<p>Details to follow.</p>", title="Annual meeting"))


def test_venue_record_still_wins():
    out = _run(BaetsExtractor, _shell("<p>online</p>", venue_name="Hilton", city="Leeds"))
    assert out["event_format"] == "in_person"


def test_helper():
    assert infer_format_from_text("face-to-face course at the hospital") == "in_person"
    assert infer_format_from_text("") is None
