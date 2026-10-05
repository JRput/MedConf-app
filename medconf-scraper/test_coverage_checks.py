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


def test_nav_and_account_links_ignored():
    ev = {**EV, "pricing_tiers": []}
    nav = '<nav><a href="/register-as-resusready">Register as ResusReady</a><a href="/registration">Registration</a></nav>'
    body = nav + '<p>Course info.</p><a href="/sign-up">Sign up for updates</a><a href="/account">Create account</a>'
    assert codes(ev, body) == []


def test_listing_chrome_link_ignored_but_event_link_kept():
    ev = {**EV, "pricing_tiers": []}
    html, text = page('<a href="/book-your-place/">Book your place</a><a href="/events/forum/registration">Register for this event</a>')
    listing = '<a href="/book-your-place/">Book your place</a>'
    ws = run_coverage_checks(ev, html, text, BASE, listing)
    assert [w.code for w in ws] == ["PRICE_SAME_SITE_LINK"]
    assert "book-your-place" not in ws[0].evidence


def test_two_day_wording_matching_row_is_clean():
    ev = {**EV, "start_date": "2026-11-05", "end_date": "2026-11-06"}
    assert codes(ev, "<p>A two-day meeting, 5-6 November 2026</p>") == []


def test_nday_in_link_to_other_course_ignored():
    ev = {**EV, "end_date": "2026-11-05"}
    assert codes(ev, '<p>e-learning plus one day face to face</p><a href="/als-2-day">ALS: 2 Day Course</a>') == []


# --- pattern 9: location on page, not stored --------------------------------
LOC_EV = {**EV, "event_format": "in_person", "city": None, "venue_name": None}
ACEP = ('<header><a href="/">ACEP</a></header><main><h1>ACEP26</h1><div class="loc"><strong>Location:</strong>'
        '<p>McCormick Place, Chicago, IL</p></div></main><footer>ACEP, 4950 W Royal Ln, Irving, TX 75063</footer>')


def test_location_on_page_acep_style():
    assert codes(LOC_EV, ACEP) == ["LOCATION_ON_PAGE"]


def test_location_jsonld():
    ld = ('<script type="application/ld+json">{"@type":"Event","location":{"@type":"Place","name":"ExCeL",'
          '"address":{"addressLocality":"London"}}}</script><p>Hi</p>')
    assert codes(LOC_EV, ld) == ["LOCATION_ON_PAGE"]


def test_location_venue_keyword_line():
    assert codes(LOC_EV, "<p>Join us</p><p>Hilton Garden Hotel</p>") == ["LOCATION_ON_PAGE"]


def test_location_online_webinar_clean():
    ev = {**LOC_EV, "event_format": "online"}
    assert codes(ev, ACEP) == []
    assert codes(LOC_EV, "<p>Location: Online via Zoom</p><p>Webinar</p>") == []


def test_location_footer_address_only_clean():
    body = "<main><p>A talk.</p></main><footer>Royal College, 12 High Street, Leeds LS1 4AB</footer>"
    assert codes(LOC_EV, body) == []


def test_location_stored_clean():
    assert codes({**LOC_EV, "city": "Chicago"}, ACEP) == []


def test_audit_city_venue_missing_with_page_evidence():
    from remediator.audit import check_city, check_venue_name
    row = {"event_format": "in_person", "city": None, "venue_name": None}
    c = check_city(row, "", f"<html><body>{ACEP}</body></html>", {})
    v = check_venue_name(row, "", f"<html><body>{ACEP}</body></html>", {})
    for r in (c, v):
        assert r.status == "MISSING" and "page names a venue/city" in r.reason
    assert check_city({**row, "event_format": "online"}, "", ACEP, {}).status == "NOT_APPLICABLE"


def test_location_on_linked_booking_page():
    from coverage_checks import location_on_linked_pages
    ev = {**LOC_EV, "booking_url": "https://chapter.example.org/conf"}
    html, text = page("<p>Location:</p><p>Hilton Columbus, Columbus, OH</p>")
    ws = location_on_linked_pages(ev, "https://acep.example/cal/x", lambda u: (html, text))
    assert [w.code for w in ws] == ["LOCATION_ON_PAGE"]
    assert location_on_linked_pages({**ev, "city": "Columbus"}, "", lambda u: (html, text)) == []
    assert location_on_linked_pages(ev, "", lambda u: (_ for _ in ()).throw(RuntimeError())) == []


def test_form_field_labels_are_not_a_location():
    body = "<form><label>Address</label><label>Address Line 2</label><label>City</label></form>"
    assert codes(LOC_EV, body) == []
