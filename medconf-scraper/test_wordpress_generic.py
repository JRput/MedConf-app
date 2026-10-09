"""Offline tests for the WordPress-generic family (Wave 2c): card parser, pagination,
date forms, location splitting, JSON-LD offers -> tiers, fee lines, REST records,
listing walk and detail extraction. No network."""
from datetime import date, timedelta

import pytest

from extractors import wordpress_generic as wg
from extractors.bcis import BcisExtractor
from extractors.bsge import BsgeExtractor
from extractors.ecco_ibd import EccoIbdExtractor
from extractors.ersnet import ErsnetExtractor
from extractors.fdi import FdiExtractor
from extractors.wordpress_generic import (
    build_page_url, fee_tiers_from_lines, find_dates, json_ld_events, location_from_ld, next_page_url,
    parse_listing_cards, pick_event_dates, rest_record_to_shell, split_location, tiers_from_offers,
)

TODAY = date(2026, 10, 9)

# ── fixtures ────────────────────────────────────────────────────────────────

ERS_HTML = """
<nav><a href="/events/menu-only-link/">Menu only</a></nav>
<ul><li><a href="https://www.ersnet.org/events/summit/">ERS Presidential Summit</a></li></ul>
<h2>Events calendar</h2>
<div class="card card__preview"><a href="https://www.ersnet.org/events/skills-course/" class="card-link"><div>
  <div class="subheading">Courses</div><div class="h5">Skills course: Interventional bronchoscopy</div>
  <div class="date caption">02 November, 2026 - 04 November, 2026</div><div class="venue caption"> Heidelberg, Germany</div>
</div></a></div>
<div class="card card__preview"><a href="https://channel.ersnet.org/media-1-webinar-3-november-2026" class="card-link" target="_blank"><div>
  <div class="subheading">Webinar</div><div class="h5">Journal club</div><div class="date caption">03 November, 2026</div>
  <div class="venue caption">Online</div></div></a></div>
<div class="pagination"><li class="pagination-next"><a href="https://www.ersnet.org/events/page/2/">next</a></li></div>
<footer><a href="/events/footer-link/">x</a></footer>
"""

BSGE_HTML = """
<div class="greybg"><a href="https://www.bsge.org.uk/event/hiflir/" title="HIFLIR Intermediate Laparoscopic &#038; Robotic Skills Course (ST1- ST4)"><h4>HIFLIR Intermediate Laparoscopic &#038; Robotic Skills...</h4></a>
<div class="edtails"><p><span>Start Date:</span> <strong>12/10/2026</strong><span>End Date:</span> <strong>13/10/2026</strong></p>
<p class="eventaddress"><span>Location:</span> <span>The Griffin Institute, Y Block, Harrow, HA1 3UJ, United Kingdom</span></p></div>
<a href="https://www.bsge.org.uk/event/hiflir/" class="btn">Find out more</a></div>
<div class="greybg"><a href="https://www.bsge.org.uk/event/webinar-76/" title="BSGE Webinar EP.76"><h4>BSGE Webinar EP.76</h4></a>
<p><span>Start Date:</span> 14/10/2026 <span>End Date:</span> 14/10/2026</p><p class="eventaddress"><span>Location:</span> <span>Zoom</span></p>
<a href="https://www.bsge.org.uk/event/webinar-76/">Find out more</a></div>
<link rel="next" href="https://www.bsge.org.uk/event/page/2/" />
"""

FDI_HTML = """
<article about="/fdi-regional-congress" class="node node--type-event node--view-mode-teaser"><div class="teaser-content">
<div class="field--name-field-n-event-type">FDI event</div>
<div class="field--name-field-n-date-range"><time datetime="2026-10-21T12:00:00Z">21 October 2026</time>
 - <time datetime="2026-10-23T12:00:00Z">23 October 2026</time></div>
<div class="teaser-title"><span class="field--name-title">FDI Regional Congress</span></div>
<div class="teaser-link"><a href="/fdi-regional-congress">Read more</a></div></div></article>
<article about="/x" class="node node--type-event"><div class="teaser-title"><span class="field--name-title">Other</span></div>
<time>9 November 2026</time><a href="/all-events?page=1">pager</a><a href="/other-event">Read more</a></article>
"""


# ── card parser ─────────────────────────────────────────────────────────────

def test_cards_ers_style_skips_menu_nav_footer_and_reads_fields():
    cards = parse_listing_cards(ERS_HTML, "https://www.ersnet.org/events/")
    by = {c["booking_url"]: c for c in cards}
    assert set(by) == {"https://www.ersnet.org/events/summit/", "https://www.ersnet.org/events/skills-course/"}  # nav/footer links and other hosts out
    c = by["https://www.ersnet.org/events/skills-course/"]
    assert c["title"] == "Skills course: Interventional bronchoscopy"
    assert (c["start_date"], c["end_date"]) == ("2026-11-02", "2026-11-04")
    assert c["venue_raw"] == "Heidelberg, Germany"
    assert c["category"] == "Courses"


def test_cards_subdomain_link_accepted_with_custom_pattern():
    cards = ErsnetExtractor({"id": 0}).parse_listing(ERS_HTML, "https://www.ersnet.org/events/")
    urls = [c["booking_url"] for c in cards]
    assert "https://channel.ersnet.org/media-1-webinar-3-november-2026" in urls
    j = next(c for c in cards if c["title"] == "Journal club")
    assert j["start_date"] == "2026-11-03" and j["venue_raw"] == "Online"


def test_cards_bsge_title_attribute_beats_truncated_heading_and_end_date_label():
    cards = parse_listing_cards(BSGE_HTML, "https://www.bsge.org.uk/event/")
    assert len(cards) == 2                                   # title + "Find out more" anchors dedupe to one card
    c = cards[0]
    assert c["title"] == "HIFLIR Intermediate Laparoscopic & Robotic Skills Course (ST1- ST4)"
    assert (c["start_date"], c["end_date"]) == ("2026-10-12", "2026-10-13")
    assert c["venue_raw"].startswith("The Griffin Institute")


def test_cards_split_by_article_with_root_level_links():
    cards = FdiExtractor({"id": 0}).parse_listing(FDI_HTML, "https://www.fdiworlddental.org/all-events")
    assert [c["booking_url"] for c in cards] == ["https://www.fdiworlddental.org/fdi-regional-congress",
                                                 "https://www.fdiworlddental.org/other-event"]
    assert cards[0]["title"] == "FDI Regional Congress"
    assert (cards[0]["start_date"], cards[0]["end_date"]) == ("2026-10-21", "2026-10-23")


def test_cards_external_links_when_allowed():
    html = ('<div class="el-item uk-card"><h4>UEG Week</h4><h5>Date</h5><p>October 17 - 20, 2026</p><h5>Location</h5><p>Barcelona, Spain</p>'
            '<a href="https://ueg.eu/p/200">Visit website</a></div><div class="el-item uk-card"><h4>No link</h4><p>March 3, 2027</p></div>')
    cards = EccoIbdExtractor({"id": 0}).parse_listing(html, "https://ecco-ibd.eu/congress-events/event-calendar")
    assert len(cards) == 1
    assert cards[0]["booking_url"] == "https://ueg.eu/p/200" and cards[0]["venue_raw"] == "Barcelona, Spain"
    assert (cards[0]["start_date"], cards[0]["end_date"]) == ("2026-10-17", "2026-10-20")


def test_cards_ignore_published_date():
    html = '<a href="https://www.x.org/events/a/">Alpha course</a><p>Posted on 7 September 2026 at 4:19 pm.</p><p>Tuesday 10 November 2026</p>'
    assert parse_listing_cards(html, "https://www.x.org/events/")[0]["start_date"] == "2026-11-10"


# ── pagination ──────────────────────────────────────────────────────────────

def test_page_url_builder_styles():
    assert build_page_url("https://a.org/events/", 2, "path") == "https://a.org/events/page/2/"
    assert build_page_url("https://a.org/events/page/2/", 3, "path") == "https://a.org/events/page/3/"
    assert build_page_url("https://a.org/events/", 2, "paged") == "https://a.org/events/?paged=2"
    assert build_page_url("https://a.org/events?cat=x&paged=2", 3, "paged") == "https://a.org/events?cat=x&paged=3"
    assert build_page_url("https://a.org/all-events", 2, "page") == "https://a.org/all-events?page=2"


def test_next_page_url_detection_and_fallback():
    cur = "https://www.bsge.org.uk/event/"
    assert next_page_url(BSGE_HTML, cur, 1) == "https://www.bsge.org.uk/event/page/2/"            # <link rel="next">
    assert next_page_url(ERS_HTML, "https://www.ersnet.org/events/", 1) == "https://www.ersnet.org/events/page/2/"  # pagination-next
    drupal = '<nav class="pager"><a href="?page=1" title="Go to next page" rel="next">next</a></nav>'
    assert next_page_url(drupal, "https://www.fdiworlddental.org/all-events", 1) == "https://www.fdiworlddental.org/all-events?page=1"
    assert next_page_url("<p>none</p>", cur, 1) is None                                           # auto: stop
    assert next_page_url("<p>none</p>", cur, 1, "path") == "https://www.bsge.org.uk/event/page/2/"  # configured style


# ── dates ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("28 October, 2026 - 29 October, 2026", ("2026-10-28", "2026-10-29")),
    ("2–4 November, 2026 | Heidelberg, Germany", ("2026-11-02", "2026-11-04")),
    ("Thursday 3rd December 2026 | One-Day", ("2026-12-03", "2026-12-03")),
    ("Monday 12 – Tuesday 13 April 2027 in Bristol", ("2027-04-12", "2027-04-13")),
    ("October 17 - 20, 2026", ("2026-10-17", "2026-10-20")),
    ("April 9 – 11, 2027", ("2027-04-09", "2027-04-11")),
    ("Dec 30, 2026 - Jan 2, 2027", ("2026-12-30", "2027-01-02")),
    ("30 Dec - 2 Jan 2027", ("2026-12-30", "2027-01-02")),
    ("Start Date: 12/10/2026 End Date: 14/10/2026", ("2026-10-12", "2026-10-14")),
    ("Start Date: 12/10/2026 End Date: 12/10/2026", ("2026-10-12", "2026-10-12")),
    ("21 October 2027 - 24 October 2027", ("2027-10-21", "2027-10-24")),
    ("2026-11-05", ("2026-11-05", "2026-11-05")),
    ("Posted on 7 September 2026 at 4:19 pm. Event on 3 Dec 2026", ("2026-12-03", "2026-12-03")),
])
def test_date_forms(text, expected):
    assert pick_event_dates(text, TODAY) == expected


def test_yearless_weekday_date_resolves_year_and_past_stays_past():
    assert pick_event_dates("Tuesday 10 November | 19:00 – 20:00 | Webinar", TODAY) == ("2026-11-10", "2026-11-10")
    assert pick_event_dates("Wednesday 18 March | Manchester", TODAY) == ("2026-03-18", "2026-03-18")   # nearest weekday match = past
    assert find_dates("no dates here 12 pm", TODAY) == []
    assert wg.find_start_time("Tuesday 10 November | 19:00 – 20:00") == "19:00"


# ── locations ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Heidelberg, Germany", (None, "Heidelberg", "Germany")),
    ("The Griffin Institute, Y Block, Harrow, HA1 3UJ, United Kingdom", ("The Griffin Institute, Y Block", "Harrow", "United Kingdom")),
    ("The Royal College of Surgeons, 38–43 Lincoln’s Inn Fields, London WC2A 3PE", ("The Royal College of Surgeons", "London", None)),
    ("Grand Mercure Bangkok Atrium, 1880 New Petchburi Road, Bangkok, 10310 - Thailand", ("Grand Mercure Bangkok Atrium", "Bangkok", "Thailand")),
    ("Amsterdam, Athens, Copenhagen, Heidelberg", (None, None, None)),                # multi-site: say nothing
    ("Online", (None, None, None)),
    ("Zoom", (None, None, None)),
    ("Lectures online | Practical | In-person | Royal College of Physicians, London", ("Royal College of Physicians", "London", None)),
    ("National Taiwan University Children's Hospital, Taiwan, China", ("National Taiwan University Children's Hospital", None, "Taiwan")),
    ("Keele University", ("Keele University", None, None)),
    ("Barcelona, Spain", (None, "Barcelona", "Spain")),
])
def test_split_location(raw, expected):
    assert split_location(raw) == expected


# ── JSON-LD ─────────────────────────────────────────────────────────────────

LD_PAGE = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},
{"@type":"Event","name":"Hands-on Course","startDate":"2026-11-20T09:00:00+00:00","endDate":"2026-11-21","eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
"location":{"@type":"Place","name":"Hilton Hotel","address":{"@type":"PostalAddress","addressLocality":"Leeds","addressCountry":"GB"}},
"offers":[{"@type":"Offer","name":"Member","price":"150.00","priceCurrency":"GBP"},{"@type":"Offer","name":"Non-member","price":"250","priceCurrency":"GBP"},
{"@type":"Offer","name":"Member","price":"150.00","priceCurrency":"GBP"},{"@type":"Offer","name":"Early bird trainee","price":"0","priceCurrency":"GBP"}],
"description":"A two-day hands-on course for registrars covering core techniques in depth."}]}</script></head>
<body><h1>Hands-on Course</h1><p>Short.</p></body></html>"""


def test_json_ld_offers_to_tiers_dedupes_and_flags_early_bird():
    ev = json_ld_events(LD_PAGE)[0]
    tiers = tiers_from_offers(ev)
    assert [(t["tier_label"], t["price_gbp"], t["currency"]) for t in tiers] == [
        ("Registration · Member", 150.0, "GBP"), ("Registration · Non-member", 250.0, "GBP"),
        ("Registration · Early bird trainee", 0.0, "GBP")]
    assert tiers[2]["is_early_bird"] is True


def test_json_ld_location():
    assert location_from_ld(json_ld_events(LD_PAGE)[0]) == ("Hilton Hotel", "Leeds", "GB", False)
    assert location_from_ld({"location": {"@type": "VirtualLocation", "url": "https://z"}})[3] is True


def test_detail_prefers_json_ld_and_keeps_listing_end_date():
    ex = BsgeExtractor({"id": 0})
    shell = {"title": "Hands-on Course", "start_date": None, "end_date": None, "venue_raw": None, "category": None}
    out = ex.detail_from_html(LD_PAGE, shell, lambda p: None)
    assert (out["start_date"], out["end_date"], out["start_time"]) == ("2026-11-20", "2026-11-21", "09:00")
    assert (out["venue_name"], out["city"], out["event_format"]) == ("Hilton Hotel", "Leeds", "in_person")
    assert len(out["pricing_tiers"]) == 3 and out["event_type"] == "course"
    assert out["specialty"] == "Obstetrics & Gynaecology"


# ── fee text ────────────────────────────────────────────────────────────────

def test_fee_lines_label_amount_pairs_eur():
    lines = ["Description", "Long paragraph " * 20, "Fees", "ERS members", "€1,000", "Non-ERS members", "€1,100", "Cancellation policy"]
    t = fee_tiers_from_lines(lines, "EUR")
    assert [(x["tier_label"], x["price_gbp"], x["currency"]) for x in t] == [
        ("Fees · ERS members", 1000.0, "EUR"), ("Fees · Non-ERS members", 1100.0, "EUR")]


def test_fee_lines_lone_amount_range_and_free():
    assert fee_tiers_from_lines(["Price", "£950", "£950"])[0]["price_gbp"] == 950.0
    assert fee_tiers_from_lines(["Price £950"])[0]["tier_label"] == "Price · Standard"
    rng = fee_tiers_from_lines(["Price £200-£350"])
    assert [(t["tier_label"], t["price_gbp"]) for t in rng] == [("Price · Lowest rate", 200.0), ("Price · Highest rate", 350.0)]
    free = fee_tiers_from_lines(["Fees: Free for ERS members and non-members"], "EUR")
    assert free[0]["price_gbp"] == 0.0 and free[0]["currency"] == "EUR"
    assert fee_tiers_from_lines(["Venue", "Leeds", "Register now"]) == []


def test_detail_fee_table_html():
    html = ("<h1>Cardiac Course</h1><p>Tuesday 10 November 2026 | Leeds General Infirmary, Leeds</p><h3>Registration Fees</h3>"
            "<table><tr><th>Category</th><th>Fee</th></tr><tr><td>Consultant</td><td>200.00</td></tr><tr><td>Trainee</td><td>100.00</td></tr></table>")
    out = BsgeExtractor({"id": 0}).detail_from_html(html, {"title": "Cardiac Course"}, lambda p: None)
    assert sorted(t["price_gbp"] for t in out["pricing_tiers"]) == [100.0, 200.0]
    assert out["start_date"] == "2026-11-10" and out["city"] == "Leeds"


def test_detail_online_category_ignores_place_line_and_header_pipe():
    out = FdiExtractor({"id": 0}).detail_from_html("<h1>Webinar x</h1><p>Body</p>", {"title": "Webinar x", "start_date": "2026-11-11", "end_date": "2026-11-11",
                                                    "venue_raw": "Honduras", "category": "CE programme"}, lambda p: None)
    assert out["event_format"] == "online" and "city" not in out
    out = BcisExtractor({"id": 0}).detail_from_html(
        "<h1>BCIS Forum</h1><p>Tuesday 10 November | 19:00 – 20:00 | Webinar | Bifurcation PCI</p>", {"title": "BCIS Forum"}, lambda p: None)
    assert out["event_format"] == "online" and "city" not in out and out["start_time"] == "19:00"


def test_detail_header_range_extends_single_day_listing_end():
    html = "<h1>Masterclass</h1><p>Thursday 3 December 2026 - Friday 4 December 2026 | Royal College of Physicians, London</p>"
    out = BcisExtractor({"id": 0}).detail_from_html(html, {"title": "Masterclass", "start_date": "2026-12-03", "end_date": "2026-12-03"}, lambda p: None)
    assert out["end_date"] == "2026-12-04" and out["venue_name"] == "Royal College of Physicians" and out["city"] == "London"


def test_detail_description_skips_cookie_text_and_llm_only_for_specialty():
    calls = []
    html = ("<h1>Generic Meeting</h1><p>Used for remembering users consent preferences to be respected on subsequent site visits and more text here.</p>"
            "<p>This meeting brings together delegates from across the region to discuss practice, share experience and plan future work.</p>")

    class Plain(wg.WordPressGenericExtractor):
        LISTING_URL = "https://x.org/events/"
        SOCIETY = "X"

    out = Plain({"id": 0}).detail_from_html(html, {"title": "Generic Meeting"}, lambda p: calls.append(p) or "Cardiology")
    assert out["description"].startswith("This meeting brings together") and out["specialty"] == "Cardiology" and len(calls) == 1


# ── REST ────────────────────────────────────────────────────────────────────

def test_rest_record_needs_event_dates_in_acf_or_meta():
    rec = {"link": "https://x.org/events/a/", "title": {"rendered": "A &amp; B"}, "date": "2026-10-06T10:00:33",
           "acf": {"event_start_date": "20261103", "event_end_date": "20261105", "venue": "Town Hall"}}
    s = rest_record_to_shell(rec)
    assert (s["title"], s["start_date"], s["end_date"], s["venue_raw"]) == ("A & B", "2026-11-03", "2026-11-05", "Town Hall")
    assert rest_record_to_shell({"link": "https://x.org/e/", "title": {"rendered": "A"}, "acf": [], "date": "2026-10-06T10:00:33"}) is None


# ── listing walk (network stubbed) ──────────────────────────────────────────

def _card(slug, d):
    return (f'<div class="card"><a href="https://x.org/events/{slug}/"><h3>{slug.title()} meeting</h3></a>'
            f'<p>{d.day} {d.strftime("%B %Y")}</p></div>')


def test_list_shells_walks_pages_filters_past_dupes_and_stops(monkeypatch):
    today = date.today()
    f1, f2, past = today + timedelta(days=20), today + timedelta(days=40), today - timedelta(days=30)
    pages = {
        "https://x.org/events/": _card("alpha", f1) + _card("old", past) + _card("alpha", f1) + '<link rel="next" href="https://x.org/events/page/2/">',
        "https://x.org/events/page/2/": _card("beta", f2) + _card("cancelled-x", f2).replace("Cancelled-X meeting", "Cancelled: X") + '<link rel="next" href="https://x.org/events/page/3/">',
        "https://x.org/events/page/3/": _card("gamma", past),
        "https://x.org/events/page/4/": _card("delta", f1),
    }
    fetched = []

    def fake_fetch(url, **kw):
        fetched.append(url)
        return pages[url].ljust(600)

    monkeypatch.setattr(wg, "fetch_html", fake_fetch)
    monkeypatch.setattr(wg.time, "sleep", lambda s: None)

    class Plain(wg.WordPressGenericExtractor):
        LISTING_URL = "https://x.org/events/"
        SOCIETY = "X"

    shells = Plain({"id": 0}).list_shells_override()
    assert [s["title"] for s in shells] == ["Alpha meeting", "Beta meeting"]
    assert "https://x.org/events/page/4/" not in fetched                  # page 3 had no next link: walk ends


def test_list_shells_far_future_placeholder_dropped_and_undated_lookup(monkeypatch):
    today = date.today()
    far = today + timedelta(days=2000)
    soon = today + timedelta(days=15)
    listing = (_card("evergreen", far) + '<div><a href="https://x.org/events/undated/"><h3>Undated course</h3></a></div>'
               '<div><a href="https://x.org/events/tbc/"><h3>Coming soon event</h3></a></div>').ljust(600)
    detail = f"<h1>Undated course</h1><p>{soon.day} {soon.strftime('%B %Y')} | Leeds, United Kingdom</p>".ljust(600)
    nodate = "<h1>Coming soon event</h1><p>More information coming soon</p>".ljust(600)

    def fake_fetch(url, **kw):
        return {"https://x.org/events/": listing, "https://x.org/events/undated/": detail, "https://x.org/events/tbc/": nodate}[url]

    monkeypatch.setattr(wg, "fetch_html", fake_fetch)
    monkeypatch.setattr(wg.time, "sleep", lambda s: None)

    class Plain(wg.WordPressGenericExtractor):
        LISTING_URL = "https://x.org/events/"
        SOCIETY = "X"

    shells = Plain({"id": 0}).list_shells_override()
    assert [s["title"] for s in shells] == ["Undated course"]
    assert shells[0]["start_date"] == soon.isoformat()
