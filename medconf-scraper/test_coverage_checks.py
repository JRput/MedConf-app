import re

from coverage_checks import run_coverage_checks, is_blocking
from test_fee_images import _png

BASE = "https://www.example.org/events/forum"
EV = {"title": "Forum", "start_date": "2026-11-05", "end_date": "2026-11-06",
      "pricing_tiers": [{"tier_label": "Member", "price_gbp": 50, "currency": "GBP"}],
      "abstract_deadline": "2026-09-01"}


def page(body):
    html = f"<html><body><main>{body}</main></body></html>"
    return html, re.sub(r"<[^>]+>", " ", html)


def codes(ev, body):
    html, text = page(body)
    return [w.code for w in run_coverage_checks(ev, html, text, BASE)]


def test_clean_page_fires_nothing():
    assert codes(EV, "<p>A one-day forum with talks.</p>") == []


def test_single_day_suspect_range():
    ev = {**EV, "end_date": "2026-11-05"}
    assert codes(ev, "<p>Join us 5-6 November 2026 in Glasgow</p>") == ["SINGLE_DAY_SUSPECT"]


def test_single_day_suspect_nday_wording():
    ev = {**EV, "end_date": None}
    assert "SINGLE_DAY_SUSPECT" in codes(ev, "<p>A two-day meeting</p>")


def test_real_single_day_ok():
    ev = {**EV, "end_date": "2026-11-05"}
    assert codes(ev, "<p>5 November 2026, one day</p>") == []


def test_price_text():
    ev = {**EV, "pricing_tiers": []}
    assert codes(ev, "<p>Members £50, non-members £90</p>") == ["PRICE_TEXT_ON_PAGE"]


def test_free_event_not_flagged():
    ev = {**EV, "pricing_tiers": []}
    assert codes(ev, "<p>This event is free to attend. Parking £5.</p>") == []


def test_price_image():
    ev = {**EV, "pricing_tiers": []}
    got = codes(ev, f"<h3>Registration</h3><p><img src=\"{_png()}\"></p>")
    assert got == ["PRICE_IMAGE_ON_PAGE"]


def test_price_external_link():
    ev = {**EV, "pricing_tiers": []}
    got = codes(ev, '<p>Registration can be found <a href="https://www.rcpsg.ac.uk/events/forum">here</a></p>')
    assert got == ["PRICE_EXTERNAL_LINK"]


def test_price_same_site_link():
    ev = {**EV, "pricing_tiers": []}
    got = codes(ev, "<ul><li><a href='/events/forum/registration'>Registration</a></li></ul>")
    assert got == ["PRICE_SAME_SITE_LINK"]


def test_tiers_present_suppress_price_warnings():
    assert codes(EV, "<p>Members £50</p><a href='/registration'>Registration</a>") == []


def test_submission_no_deadline():
    ev = {**EV, "abstract_deadline": None}
    got = codes(ev, "<h2>Call for Papers</h2><p>We invite submissions.</p>")
    assert got == ["SUBMISSION_NO_DEADLINE"]


def test_submission_with_note_ok():
    ev = {**EV, "abstract_deadline": None, "abstract_deadline_note": "see PDF"}
    assert codes(ev, "<h2>Call for Papers</h2>") == []


def test_cta_in_tier_label():
    ev = {**EV, "pricing_tiers": [{"tier_label": "Register and save Members", "price_gbp": 50}]}
    assert codes(ev, "<p>x</p>") == ["CTA_IN_TIER_LABEL"]


def test_duplicate_tiers():
    t = {"tier_label": "Member", "price_gbp": 50, "currency": "GBP"}
    assert codes({**EV, "pricing_tiers": [t, dict(t)]}, "<p>x</p>") == ["DUPLICATE_TIERS"]


def test_blocking_classification():
    html, text = page("<h2>Call for Papers</h2>")
    ws = run_coverage_checks({**EV, "abstract_deadline": None}, html, text, BASE)
    assert any(is_blocking(w) for w in ws)
