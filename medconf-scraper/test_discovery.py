"""Scrape-time discovery engine (ticket X3). No network: fetch/PDF/vision seams are
monkeypatched with canned HTML, PDF bytes and image tiers."""
import types

import pytest

from extractors import discovery
from extractors.discovery import (
    DiscoveryBudget, DiscoveryHints, VisionLedger, apply_to_row, discover, missing_fields,
)

BASE = "https://conf.example.org/event/annual-2027/"

MAIN = """<html><body><nav>
<a href="/event/annual-2027/registration">Registration</a>
<a href="/event/annual-2027/travel">Travel</a>
<a href="/event/annual-2027/call-for-papers">Call for papers</a>
</nav><h1>Annual Meeting 2027</h1><p>Welcome to the Annual Meeting.</p></body></html>"""

REG = """<html><body><h2>Registration fees</h2>
<p>Member: £120</p><p>Non-member: £180</p><p>Student: £60</p></body></html>"""

TRAVEL = """<html><body><h1>Travel</h1><div>
<p>The meeting takes place at the Grand Hall</p>
<p>Grand Hall, 12 Queen Street, Leeds, LS1 4AB</p></div></body></html>"""

MAPS = ('<html><body><h1>Getting there</h1><iframe src="https://www.google.com/maps?q='
        'ICM+Munich,+Am+Messesee+6,+Munich,+Germany&output=embed"></iframe></body></html>')

CFP = """<html><body><h1>Call for papers</h1>
<p>Abstract submission deadline: 30 June 2099.</p><p>Submit your abstract online.</p></body></html>"""


class Net:
    """Canned web: url -> html. Records every fetch."""
    def __init__(self, pages):
        self.pages, self.fetched = pages, []

    def __call__(self, url, timeout):
        self.fetched.append(url)
        return self.pages.get(url)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"unexpected fetch {u}"))
    monkeypatch.setattr(discovery, "_fetch_bytes", lambda *a, **k: pytest.fail("unexpected pdf fetch"))
    monkeypatch.setattr(discovery, "_vision_pricing", lambda *a, **k: pytest.fail("unexpected vision"))
    monkeypatch.setattr(discovery, "_vision_allowed", lambda: True)


def row(**kw):
    r = {"conference_name": "Annual Meeting 2027", "start_date": "2099-09-01", "event_format": "in_person",
         "pricing_tiers": [], "venue_name": None, "city": None}
    r.update(kw)
    return r


def go(r, html=MAIN, net=None, **kw):
    if net is not None:
        discovery._fetch_html = net
    return discover(r, html, "", BASE, **kw)


# --------------------------------------------------------------------------
def test_missing_fields():
    assert set(missing_fields(row())) == {"fees", "venue", "abstract"}
    full = row(pricing_tiers=[{"x": 1}], venue_name="V", city="C", abstract_open=True)
    assert missing_fields(full) == []
    assert "venue" not in missing_fields(row(event_format="online"))


def test_fees_found_on_registration_subpage(monkeypatch):
    net = Net({BASE + "registration": REG})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(row(), MAIN, "", BASE)
    assert len(res.tiers) == 3
    assert {t["currency"] for t in res.tiers} == {"GBP"}
    assert any(t["price_gbp"] == 120 for t in res.tiers)
    step = [e for e in res.evidence if e["step"].startswith("fetch:fees")][0]
    assert step["url"].endswith("/registration") and step["found"] and "elapsed_ms" in step
    assert len(net.fetched) <= 2


def test_eu_decimal_fee_on_subpage(monkeypatch):
    page = "<html><body><h2>Fees</h2><p>Standard fee 2026 (incl. VAT) EUR 3.450,00</p></body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": page}))
    res = discover(row(), MAIN, "", BASE)
    assert [(t["price_gbp"], t["currency"]) for t in res.tiers] == [(3450.0, "EUR")]


def test_side_charges_and_currencyless_amounts_are_not_fees(monkeypatch):
    page = ("<html><body><h2>Registration</h2><p>Cancellation fee £50</p><p>Parking £10</p>"
            "<p>Hotel per night £120</p><p>Delegate 300</p></body></html>")
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": page}))
    assert discover(row(), MAIN, "", BASE).tiers == []


def test_fees_in_pdf(monkeypatch):
    main = '<html><body><a href="/files/registration-brochure.pdf">Registration brochure</a></body></html>'
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail("no html follow expected"))
    monkeypatch.setattr(discovery, "_fetch_bytes", lambda u, t, m=8_000_000: b"%PDF-1.4 fake")
    monkeypatch.setattr(discovery, "_pdf_text", lambda d, timeout=20.0: "Registration fees\nDelegate £200\nStudent £90\n" + "x" * 50)
    res = discover(row(event_format="online"), main, "", BASE)
    assert sorted(t["price_gbp"] for t in res.tiers) == [90.0, 200.0]
    assert any(e["step"].startswith("pdf:fees") for e in res.evidence)


def test_pdf_rejected_returns_nothing(monkeypatch):
    main = '<a href="/files/registration-brochure.pdf">Registration brochure</a>'
    monkeypatch.setattr(discovery, "_fetch_bytes", lambda *a, **k: None)
    res = discover(row(event_format="online"), main, "", BASE)
    assert res.tiers == [] and res.evidence[-1]["found"] == ["fetch_rejected"]


IMG_PAGE = ('<html><body><h2>Registration fees</h2>'
            '<img src="/img/fee-table.png" width="900" height="700" alt="Registration fee table">'
            '</body></html>')


def test_fee_image_read_by_vision_within_budget(monkeypatch):
    seen = []
    monkeypatch.setattr(discovery, "_vision_pricing", lambda urls, stop_at, timeout=None: seen.append(urls) or [
        {"tier_label": "Member", "price_gbp": 150.0, "currency": "EUR", "is_early_bird": False},
        {"tier_label": "Guess", "price_gbp": 99.0, "currency": None, "is_early_bird": False}])
    led = VisionLedger()
    res = discover(row(event_format="online"), IMG_PAGE, "", BASE, budget=DiscoveryBudget(vision=led))
    assert [(t["tier_label"], t["currency"]) for t in res.tiers] == [("Member", "EUR")]  # null currency dropped
    assert led.images_used == 1 and seen and res.deferred == []


def test_fee_image_deferred_beyond_budget(monkeypatch):
    led = VisionLedger(images_used=5)
    res = discover(row(event_format="online"), IMG_PAGE, "", BASE, budget=DiscoveryBudget(vision=led))
    assert res.tiers == [] and res.deferred == ["fee_image_pending"]


def test_fee_image_deferred_when_vision_seconds_spent(monkeypatch):
    led = VisionLedger(seconds_used=119.0)
    res = discover(row(event_format="online"), IMG_PAGE, "", BASE, budget=DiscoveryBudget(vision=led))
    assert res.deferred == ["fee_image_pending"]


def test_inline_data_image_goes_to_vision(monkeypatch):
    page = ('<h2>Registration fees</h2><img src="data:image/png;base64,' + "A" * 60000 +
            '" width="800" height="600">')
    got = []
    monkeypatch.setattr(discovery, "_vision_pricing", lambda urls, stop_at, timeout=None: got.append(urls[0][:21]) or [
        {"tier_label": "Delegate", "price_gbp": 10.0, "currency": "USD"}])
    res = discover(row(event_format="online"), page, "", BASE)
    assert got == ["data:image/png;base64"] and res.tiers[0]["currency"] == "USD"


def test_no_vision_in_safe_mode(monkeypatch):
    monkeypatch.setattr(discovery, "_vision_allowed", lambda: False)
    res = discover(row(event_format="online"), IMG_PAGE, "", BASE)
    assert res.deferred == ["fee_image_pending"]


def test_venue_from_travel_page_address_block(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "travel": TRAVEL}))
    res = discover(row(pricing_tiers=[{"a": 1}], abstract_open=True), MAIN, "", BASE)
    assert res.city == "Leeds"                      # a bare street address yields the city
    assert any(e["found"] == ["venue:address_block"] for e in res.evidence)


def test_venue_name_from_venue_line_on_travel_page(monkeypatch):
    page = "<html><body><h1>Travel</h1><p>Venue: Grand Hall, Queen Street, Leeds</p></body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "travel": page}))
    res = discover(row(pricing_tiers=[{"a": 1}], abstract_open=True), MAIN, "", BASE)
    assert res.venue_name.startswith("Grand Hall") and res.city == "Leeds"


def test_venue_from_maps_embed(monkeypatch):
    main = '<a href="/event/annual-2027/travel">Travel</a>'
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "travel": MAPS}))
    res = discover(row(pricing_tiers=[{"a": 1}], abstract_open=True), main, "", BASE)
    assert res.venue_name == "ICM Munich" and res.city == "Munich"


def test_abstract_deadline_from_call_for_papers_page(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "call-for-papers": CFP}))
    res = discover(row(pricing_tiers=[{"a": 1}], event_format="online"), MAIN, "", BASE)
    assert res.abstract_deadline == "2099-06-30" and res.abstract_open is True


def test_skip_urls_not_refetched(monkeypatch):
    net = Net({BASE + "call-for-papers": CFP})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(row(pricing_tiers=[{"a": 1}], event_format="online"), MAIN, "", BASE,
                   skip_urls=[BASE + "call-for-papers"])
    assert net.fetched == [] and not res.has_abstract()


def test_at_most_two_html_fetches(monkeypatch):
    net = Net({})                                  # every fetch fails -> keeps trying candidates
    monkeypatch.setattr(discovery, "_fetch_html", net)
    discover(row(), MAIN, "", BASE)
    assert len(net.fetched) == 2


def test_budget_exhaustion_returns_partial_evidence(monkeypatch):
    ticks = iter(range(0, 1000, 15))               # every clock read advances 15 s
    net = Net({BASE + "registration": REG})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(row(), MAIN, "", BASE, budget=DiscoveryBudget(clock=lambda: float(next(ticks))))
    assert net.fetched == [] and res.tiers == []
    assert [e["step"] for e in res.evidence] == ["page"]


def test_hints_are_tried_first(monkeypatch):
    net = Net({BASE.rstrip("/") + "/delegate-fees": REG})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    hints = DiscoveryHints(fees_suffixes=("/delegate-fees",))
    res = discover(row(), MAIN, "", BASE, hints=hints)
    assert net.fetched[0].endswith("/delegate-fees") and len(res.tiers) == 3
    assert any(e["step"] == "fetch:fees:hint" for e in res.evidence)


def test_hint_url_template_and_anchor_words(monkeypatch):
    net = Net({"https://conf.example.org/2099/fees": REG})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    hints = DiscoveryHints(fees_urls=("{base}/{year}/fees",))
    assert len(discover(row(), MAIN, "", BASE, hints=hints).tiers) == 3
    page = '<a href="/x/rates-info">Delegate rates</a>'
    net2 = Net({"https://conf.example.org/x/rates-info": REG})
    monkeypatch.setattr(discovery, "_fetch_html", net2)
    hints2 = DiscoveryHints(anchor_words={"fees": ("delegate rates",)})
    # an anchor-word link is picked from the page, not declared by the hint: it needs its own STRONG identity
    assert discover(row(event_format="online"), page, "", BASE, hints=hints2).tiers == []
    net2.pages["https://conf.example.org/x/rates-info"] = REG.replace("<body>", "<body><h1>Annual Meeting 2027 Registration</h1>")
    assert len(discover(row(event_format="online"), page, "", BASE, hints=hints2).tiers) == 3


def test_external_hop_to_organiser_url_is_identity_gated(monkeypatch):
    org = "https://camls.example.net/programs/course"
    page = ("<html><body><h1>Minimally Invasive Course</h1><h2>Registration fees</h2>"
            "<p>Physicians Early Fee $2,699</p><p>Physicians Late Fee $2,999</p></body></html>")
    monkeypatch.setattr(discovery, "_fetch_html", Net({org: page}))
    r = row(conference_name="Minimally Invasive Course", event_format="online", organiser_url=org)
    res = discover(r, "<html><body>info</body></html>", "", BASE)
    assert [t["currency"] for t in res.tiers] == ["USD", "USD"]
    assert any(e["step"].endswith(":external") for e in res.evidence)
    # a page that is not about this event is refused
    monkeypatch.setattr(discovery, "_fetch_html", Net({org: page.replace("Minimally Invasive Course", "Other thing")}))
    r2 = row(conference_name="Quite Different Symposium", event_format="online", organiser_url=org)
    res2 = discover(r2, "<html><body>info</body></html>", "", BASE)
    assert res2.tiers == [] and any(e.get("identity") == "weak" for e in res2.evidence)


def test_external_links_other_than_organiser_url_never_followed(monkeypatch):
    net = Net({})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    main = '<a href="https://elsewhere.org/registration">Registration</a>'
    discover(row(event_format="online", abstract_open=True), main, "", BASE)
    assert net.fetched == []


def test_never_raises_and_no_llm(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: 1 / 0)
    res = discover(row(), MAIN, "", BASE)
    assert res.tiers == []


# --------------------------------------------------------------------------
def test_apply_to_row_fills_only_empty_fields():
    res = discovery.DiscoveryResult(
        tiers=[{"tier_label": "A", "price_gbp": 1.0, "currency": "GBP"}],
        venue_name="New Venue", city="New City", abstract_open=True, abstract_deadline="2099-01-01")
    r = {"pricing_tiers": [{"keep": 1}], "venue_name": "Old Venue", "city": None, "abstract_deadline_note": "n"}
    written = apply_to_row(r, res)
    assert r["pricing_tiers"] == [{"keep": 1}] and r["venue_name"] == "Old Venue"
    assert r["city"] == "New City" and "abstract_deadline" not in r
    assert written == ["city"]
    r2 = {}
    assert set(apply_to_row(r2, res)) == {"pricing_tiers", "venue_name", "city", "abstract"}
    assert r2["abstract_deadline"] == "2099-01-01"


def _agent(extractor, html=MAIN):
    page = types.SimpleNamespace(content=lambda: html, url=BASE)
    browser = types.SimpleNamespace(page=page, get_page_text=lambda: "Annual Meeting")
    return types.SimpleNamespace(extractor=extractor, browser=browser)


def test_agent_merge_hook_fills_and_records_evidence(monkeypatch):
    from llm_agent import AgentLoop
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": REG, BASE + "travel": TRAVEL}))
    ag = _agent(types.SimpleNamespace())
    merged = row(venue_name=None, city=None, description="d")
    AgentLoop._discover_missing(ag, merged, BASE)
    assert len(merged["pricing_tiers"]) == 3 and merged["city"] == "Leeds"
    ev = merged["_discovery_evidence"]
    assert "pricing_tiers" in ev["filled"] and ev["evidence"]
    assert isinstance(ag._vision_ledger, VisionLedger)


def test_agent_merge_hook_respects_discovery_enabled_false(monkeypatch):
    from llm_agent import AgentLoop
    ag = _agent(types.SimpleNamespace(DISCOVERY_ENABLED=False))
    merged = row()
    AgentLoop._discover_missing(ag, merged, BASE)       # autouse fixture fails on any fetch
    assert merged["pricing_tiers"] == [] and "_discovery_evidence" not in merged


def test_agent_merge_hook_leaves_extractor_values(monkeypatch):
    from llm_agent import AgentLoop
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": REG}))
    ag = _agent(types.SimpleNamespace())
    tiers = [{"tier_label": "Mine", "price_gbp": 5.0, "currency": "GBP"}]
    merged = row(pricing_tiers=tiers, venue_name="V", city="C", abstract_open=True)
    AgentLoop._discover_missing(ag, merged, BASE)       # nothing missing -> no fetch at all
    assert merged["pricing_tiers"] == tiers and "_discovery_evidence" not in merged


def test_agent_hook_passes_hints_and_shared_ledger(monkeypatch):
    from llm_agent import AgentLoop
    net = Net({BASE.rstrip("/") + "/delegate-fees": REG})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    ag = _agent(types.SimpleNamespace(DISCOVERY_HINTS=DiscoveryHints(fees_suffixes=("/delegate-fees",))))
    AgentLoop._discover_missing(ag, row(), BASE)
    assert net.fetched[0].endswith("/delegate-fees")
    led = ag._vision_ledger
    AgentLoop._discover_missing(ag, row(), BASE)
    assert ag._vision_ledger is led                     # one ledger per source run


def test_base_extractor_defaults():
    from extractors.base import BaseExtractor
    assert BaseExtractor.DISCOVERY_ENABLED is True and BaseExtractor.DISCOVERY_HINTS is None


# --------------------------------------------------------------------------
# precision rules found by the live proof (2026-10-27)
# --------------------------------------------------------------------------
def test_two_amounts_on_a_line_get_their_own_labels(monkeypatch):
    page = ("<html><body><h2>Registration</h2><p>Physicians - Main Course only</p>"
            "<p>Early Fee - $2,699 and Late Fee $2,999</p><p>Residents</p>"
            "<p>Early Fee - $1,500 and Late Fee $1,800</p></body></html>")
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": page}))
    res = discover(row(event_format="online", abstract_open=True), MAIN, "", BASE)
    labels = {(t["tier_label"], t["price_gbp"]) for t in res.tiers}
    assert ("Physicians - Main Course only · Early Fee", 2699.0) in labels
    assert ("Residents · Late Fee", 1800.0) in labels and len(labels) == 4


def test_same_label_at_different_prices_is_ambiguous_and_dropped(monkeypatch):
    page = ("<html><body><h2>Course fees</h2><p>Standard fee (incl. VAT)</p><p>EUR 3.450,00</p>"
            "<p>Standard fee (incl. VAT)</p><p>EUR 3.540,00</p></body></html>")
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": page}))
    assert discover(row(event_format="online", abstract_open=True), MAIN, "", BASE).tiers == []


def test_amount_first_card_layout(monkeypatch):
    page = "<html><body><h2>Fees</h2><div>EUR 3.450,00</div><div>Standard fee 2026 (incl. VAT)</div></body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": page}))
    res = discover(row(event_format="online", abstract_open=True), MAIN, "", BASE)
    assert [(t["tier_label"], t["price_gbp"], t["currency"]) for t in res.tiers] == \
        [("Standard fee 2026 (incl. VAT)", 3450.0, "EUR")]


def test_banner_split_only_when_unambiguous():
    f = discovery._split_banner
    assert f("February 28 - March 3, 2027 JW Marriott Los Angeles L.A. Live Los Angeles, California") == \
        {"venue_name": "JW Marriott Los Angeles L.A. Live", "city": "Los Angeles", "method": "banner_split"}
    assert f("Feb 1, 2027 Some Hall Bristol, UK") is None          # city not repeated in the venue: no guess


def test_venue_from_banner_on_the_page_itself(monkeypatch):
    page = ("<html><body><h1>AACR IO</h1><p>February 28 - March 3, 2027 JW Marriott Los Angeles L.A. Live "
            "Los Angeles, California</p></body></html>")
    res = discover(row(pricing_tiers=[{"a": 1}], abstract_open=True), page, "", BASE)
    assert res.venue_name == "JW Marriott Los Angeles L.A. Live" and res.city == "Los Angeles"
    assert res.evidence[0]["step"] == "page"


def test_second_hop_from_organiser_homepage_to_its_abstracts_page(monkeypatch):
    org = "https://emuc.example.net/"
    home = ('<html><body><h1>Zebrafish Symposium 2027</h1>'
            '<a href="/scientific-programme/abstracts/">Abstract Submission</a> Welcome</body></html>')
    abs_ = ("<html><body><h1>Zebrafish Symposium 2027 abstracts</h1>"
            "<p>Abstract submission deadline: 1 August 2099. Submit your abstract.</p></body></html>")
    net = Net({org: home, "https://emuc.example.net/scientific-programme/abstracts/": abs_})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    r = row(pricing_tiers=[{"a": 1}], event_format="online", organiser_url=org,
            conference_name="Zebrafish Symposium 2027")
    res = discover(r, "<html><body>stub</body></html>", "", BASE)
    assert res.abstract_deadline == "2099-08-01" and len(net.fetched) == 2
    # FV4 trade-off: a homepage whose heading is not the event title is WEAK -> no second hop
    net.pages[org] = home.replace("<h1>Zebrafish Symposium 2027</h1>", "")
    net.fetched.clear()
    res = discover(r, "<html><body>stub</body></html>", "", BASE)
    assert not res.has_abstract() and net.fetched == [org]


def test_site_wide_pages_that_never_name_the_field_are_not_fetched(monkeypatch):
    main = ('<a href="/trainees/cost-of-training">Cost of training</a>'
            '<a href="/patient-info">Patient info</a><a href="/awards/travel-grants">Travel grants</a>')
    net = Net({})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    discover(row(), main, "", "https://www.society.org/event/some-event.html")
    assert net.fetched == []


def test_external_event_site_named_in_a_link_address(monkeypatch):
    url = "https://camls.example.net/programs/minimally-invasive-gynecologic-surgery-course/"
    main = f'<a href="{url}">{url}</a>'
    page = ("<html><body><h1>Minimally Invasive Gynecologic Surgery Course</h1><h2>Registration</h2>"
            "<p>Early Fee - $2,699</p><p>Late Fee - $2,999</p></body></html>")
    net = Net({url: page})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    r = row(conference_name="Minimally Invasive Gynecologic Surgery Course", event_format="online",
            abstract_open=True)
    res = discover(r, main, "", "https://aagl.example.org/event/x/y/")
    assert sorted(t["price_gbp"] for t in res.tiers) == [2699.0, 2999.0]
    assert res.evidence[-1]["step"].endswith("linked_event_site:external")


def test_generic_topic_words_do_not_make_an_external_link_this_event():
    main = '<a href="https://podcasts.example.com/emergency-medicine-audio-network">listen</a>'
    r = row(conference_name="StEMI X Stanford Emergency Medicine Innovation Symposium")
    assert discovery._external_by_slug(main, "https://acep.example.org/e/x", r) == []


def test_ticketing_host_uses_identity_and_date_gated_handler(monkeypatch):
    ld = ('{"@type":"Event","name":"Zebrafish Symposium 2027","startDate":"2099-09-01",'
          '"offers":[{"@type":"Offer","name":"Standard","price":"45","priceCurrency":"GBP"}]}')
    page = f'<html><head><script type="application/ld+json">{ld}</script></head><body><h1>Zebrafish Symposium 2027</h1></body></html>'
    eb = "https://www.eventbrite.co.uk/e/annual-meeting-2027-tickets-1"
    monkeypatch.setattr(discovery, "_fetch_html", Net({eb: page}))
    zr = dict(event_format="online", abstract_open=True, organiser_url=eb, conference_name="Zebrafish Symposium 2027")
    res = discover(row(**zr), "<html><body>stub</body></html>", "", BASE)
    assert [(t["tier_label"], t["price_gbp"], t["currency"]) for t in res.tiers] == [("Standard", 45.0, "GBP")]
    # a different occurrence (other date) must not be taken
    monkeypatch.setattr(discovery, "_fetch_html", Net({eb: page.replace("2099-09-01", "2099-12-12")}))
    assert discover(row(**zr), "<html><body>stub</body></html>", "", BASE).tiers == []


def test_explorer_names_missing_falls_back_to_local_matchers(monkeypatch):
    """X2 edits explorer.py concurrently: every picker name is optional."""
    monkeypatch.setattr(discovery, "_explorer", lambda: None)
    net = Net({BASE + "registration": REG, BASE + "travel": TRAVEL})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(row(), MAIN, "", BASE)
    assert len(res.tiers) == 3 and res.city == "Leeds"


# ═══ FV1 review fixes (opus verdict FAIL, 2026-10-27) ═══════════════════════════════
CARDIO = "https://soc.org/events/conferences/cardio-update-2027"
NEURO = "https://soc.org/events/conferences/neuro-masterclass-2027"
CARDIO_PAGE = (f'<html><body><h1>Cardio Update 2027</h1><p>Details coming soon.</p>'
               f'<aside><h3>Other events</h3><a href="{NEURO}">Register now: Neuro Masterclass</a></aside></body></html>')
NEURO_PAGE = """<html><body><h1>Neuro Masterclass 2027</h1><h2>Registration fees</h2>
<table><tr><th>Category</th><th>Fee</th></tr><tr><td>Member</td><td>£250</td></tr>
<tr><td>Non-member</td><td>£350</td></tr></table>
<h2>Venue</h2><p>Venue: Royal Hall, Edinburgh</p></body></html>"""


def cardio_row(**kw):
    return row(conference_name="Cardio Update 2027", start_date="2027-03-01", **kw)


def test_in_event_path_is_the_events_own_path_not_its_parent():
    assert discovery._in_event_path(CARDIO, CARDIO + "/registration")
    assert not discovery._in_event_path(CARDIO, NEURO)                 # a sibling is not "inside"
    assert not discovery._in_event_path(CARDIO, "https://soc.org/events/conferences/")
    assert not discovery._in_event_path(CARDIO, "https://other.org" + "/events/conferences/cardio-update-2027/x")


def test_sibling_event_link_feeds_nothing(monkeypatch):
    """Reviewer T1: a related-events 'Register now' link to a sibling must not give the row
    the sibling's fees or venue."""
    net = Net({NEURO: NEURO_PAGE})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(cardio_row(), CARDIO_PAGE, "", CARDIO)
    assert net.fetched == [NEURO]                                      # it was looked at ...
    assert res.tiers == [] and res.venue_name is None and res.city is None   # ... and nothing was used
    miss = [e for e in res.evidence if e.get("reason") == "identity_mismatch"]
    assert miss and miss[0]["url"] == NEURO


def test_same_host_page_outside_own_path_must_name_the_event(monkeypatch):
    page = '<html><body><a href="/info/delegate-registration">Registration</a></body></html>'
    row_ = cardio_row()
    other = "https://soc.org/info/delegate-registration"
    generic = '<html><body><h1>Delegate registration</h1><p>Member: £100</p><p>Non-member: £150</p></body></html>'
    monkeypatch.setattr(discovery, "_fetch_html", Net({other: generic}))
    res = discover(row_, page, "", CARDIO)
    assert res.tiers == [] and any(e.get("reason") == "weak_identity" for e in res.evidence)
    named = generic.replace("<p>Member", "<p>Cardio Update 2027 delegates</p><p>Member")
    monkeypatch.setattr(discovery, "_fetch_html", Net({other: named}))
    assert discover(row_, page, "", CARDIO).tiers == []          # FV4: the title in the body is not identity
    titled = generic.replace("Delegate registration", "Cardio Update 2027: Registration")
    monkeypatch.setattr(discovery, "_fetch_html", Net({other: titled}))
    assert len(discover(row_, page, "", CARDIO).tiers) == 2


def test_rejected_page_links_are_not_followed(monkeypatch):
    """The rejected sibling page offers NO fees or venue, so an engine without the gate is
    never 'satisfied' by it and goes on to its links: they must still never be fetched."""
    bad = ("<html><body><h1>Neuro Masterclass 2027</h1><p>Programme to follow.</p>"
           f"<a href='{NEURO}/registration'>Registration</a><a href='{NEURO}/venue'>Venue</a>"
           "<a href='/files/fees.pdf'>Registration fees PDF</a></body></html>")
    net = Net({NEURO: bad})                     # autouse fixture fails any PDF fetch
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(cardio_row(), CARDIO_PAGE, "", CARDIO, budget=DiscoveryBudget(max_html=3))
    assert net.fetched == [NEURO]
    assert [e.get("reason") for e in res.evidence if e["step"].startswith("fetch")] == ["identity_mismatch"]


SHARED = """<html><body><h1>Events calendar</h1>
<div><h2>Webinar on Sepsis</h2><p>Registration fees</p><p>Member: $50</p><p>Non-member: $80</p>
<a href="/calendar/sepsis/register">Register</a></div>
<div><h2>ICU Leadership Summit</h2><p>Registration fees</p><p>Delegate: $400</p><p>Student: $150</p></div>
</body></html>"""


def test_fragment_row_on_shared_page_gets_no_scrape_time_discovery(monkeypatch):
    """Reviewer T2 (FV4): a #fragment row is skipped entirely, no window parsing."""
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"followed {u}"))
    for name, frag in (("ICU Leadership Summit", "#icu-leadership-summit-ab12"), ("Webinar on Sepsis", "#sepsis")):
        res = discover(row(conference_name=name), SHARED, "", "https://sccm.org/calendar" + frag)
        assert res.tiers == [] and res.venue_name is None and res.evidence[0]["reason"] == "shared_page"


def test_shared_flag_skips_even_without_a_fragment(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"followed {u}"))
    res = discover(row(conference_name="ICU Leadership Summit"), SHARED, "", "https://sccm.org/calendar", shared=True)
    assert res.tiers == [] and [e["step"] for e in res.evidence] == ["skip"]
    r = row(conference_name="ICU Leadership Summit", booking_url="https://sccm.org/calendar#icu")
    assert discover(r, SHARED, "", "https://sccm.org/calendar").evidence[0]["reason"] == "shared_page"


def test_shared_page_info_keys():
    from llm_agent import shared_page_info
    shells = [{"title": "Sepsis Update", "booking_url": "https://x.org/cal"},
              {"title": "Sepsis Update Advanced", "booking_url": "https://x.org/cal?page=2"},
              {"title": "Other", "booking_url": "https://x.org/other"}]
    shared, sibs = shared_page_info(shells, "https://x.org/cal")
    assert shared and sorted(sibs) == ["Sepsis Update", "Sepsis Update Advanced"]
    assert shared_page_info(shells, "https://x.org/other") == (False, ["Other"])
    assert shared_page_info([], "https://x.org/cal#frag")[0] is True


def test_agent_hook_skips_a_page_shared_by_two_shells(monkeypatch):
    from llm_agent import AgentLoop
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"followed {u}"))
    html = ("<html><body><h2>Annual Meeting 2027</h2><p>Registration fees</p><p>Member: £120</p>"
            "<p>Student: £60</p><h2>Other Webinar 2027</h2><p>Registration fees</p><p>Member: £5</p>"
            "<p>Student: £3</p></body></html>")
    ag = _agent(types.SimpleNamespace(), html=html)
    ag.shells = [{"title": "Annual Meeting 2027", "booking_url": BASE}, {"title": "Other Webinar 2027", "booking_url": BASE}]
    merged = row(venue_name="V", city="C", abstract_open=True)
    AgentLoop._discover_missing(ag, merged, BASE)
    assert merged["pricing_tiers"] == []
    assert merged["_discovery_evidence"]["evidence"] == [
        {"step": "skip", "reason": "shared_page", "url": BASE, "found": [], "elapsed_ms": 0}]


# ---- wall clock is enforced INSIDE steps ----------------------------------------------
class FakeClock:
    def __init__(self):
        self.t, self.calls = 0.0, []

    def __call__(self):
        return self.t


PDF_PAGE = ("<html><body><a href='/e/a/b/registration'>Registration</a><a href='/e/a/b/venue'>Venue</a>"
            "<a href='/f/registration-fees.pdf'>Registration fees</a></body></html>")


def _slow_world(monkeypatch, clk, html_cost, pdf_get_cost=None, pdf_parse_cost=20.0):
    def html(url, timeout):
        clk.calls.append(("html", timeout)); clk.t += min(html_cost, timeout)
        return "<html><p>nothing</p></html>"

    def pdfget(url, timeout, mx=0):
        clk.calls.append(("pdfget", timeout)); clk.t += timeout if pdf_get_cost is None else min(pdf_get_cost, timeout)
        return b"%PDF-1.4"

    def pdftext(data, timeout=20.0):
        clk.calls.append(("pdfparse", timeout)); clk.t += min(pdf_parse_cost, timeout)
        return "x " * 50

    monkeypatch.setattr(discovery, "_fetch_html", html)
    monkeypatch.setattr(discovery, "_fetch_bytes", pdfget)
    monkeypatch.setattr(discovery, "_pdf_text", pdftext)


def test_slow_pdf_fetch_cannot_push_the_total_past_the_wall(monkeypatch):
    """Reviewer T3b: 37 s against a 20 s wall (15 s fetch + a 20 s child parse)."""
    clk = FakeClock()
    _slow_world(monkeypatch, clk, html_cost=1.0)
    discover({"conference_name": "Wall Test Congress", "event_format": "in_person"}, PDF_PAGE, "",
             "https://h.org/a/b/c", budget=DiscoveryBudget(clock=clk))
    kinds = [c[0] for c in clk.calls]
    assert "pdfget" in kinds and "pdfparse" in kinds
    assert clk.t <= 20.0 + 1e-9
    fetch_t = dict(clk.calls[-2:])["pdfget"]
    parse_t = dict(clk.calls[-2:])["pdfparse"]
    assert parse_t >= discovery.PDF_MIN_PARSE and fetch_t + parse_t <= 20.0 - 2.0


def test_pdf_step_skipped_when_clock_cannot_cover_fetch_plus_parse(monkeypatch):
    clk = FakeClock()
    _slow_world(monkeypatch, clk, html_cost=7.0)          # two page fetches use 14 of 18 s
    discover({"conference_name": "Wall Test Congress", "event_format": "in_person"}, PDF_PAGE, "",
             "https://h.org/a/b/c", budget=DiscoveryBudget(clock=clk, wall_seconds=18.0))
    assert [c[0] for c in clk.calls] == ["html", "html"]  # 4 s left < PDF_MIN_FETCH + PDF_MIN_PARSE
    assert clk.t <= 18.0


def test_every_step_timeout_fits_in_what_is_left(monkeypatch):
    """Hung hosts (every fetch burns its full timeout). Observable guards:
    (a) 0.5 s left after the first fetch is below the 1 s reserve -> the 2nd fetch never starts;
    (b) 2 s left -> the 2nd fetch is given exactly 2 s, and the PDF step (needs fetch + parse
        reserve) is skipped."""
    ev = {"conference_name": "Wall Test Congress", "event_format": "in_person"}
    clk = FakeClock()
    _slow_world(monkeypatch, clk, html_cost=100.0)
    discover(ev, PDF_PAGE, "", "https://h.org/a/b/c", budget=DiscoveryBudget(clock=clk, wall_seconds=10.5))
    assert clk.calls == [("html", 10.0)] and clk.t <= 10.5
    clk = FakeClock()
    _slow_world(monkeypatch, clk, html_cost=100.0)
    discover(ev, PDF_PAGE, "", "https://h.org/a/b/c", budget=DiscoveryBudget(clock=clk, wall_seconds=12.0))
    assert clk.calls == [("html", 10.0), ("html", 2.0)] and clk.t <= 12.0
    # (c) 4 s left after two 6 s fetches: below the PDF reserve (fetch 2 s + child parse 3 s),
    #     so the PDF step is never started (the pre-fix engine started it above 3 s)
    clk = FakeClock()
    _slow_world(monkeypatch, clk, html_cost=6.0)
    discover(ev, PDF_PAGE, "", "https://h.org/a/b/c", budget=DiscoveryBudget(clock=clk, wall_seconds=16.0))
    assert [c[0] for c in clk.calls] == ["html", "html"] and clk.t <= 16.0


# ═══ FV4 fail-closed identity gate (V cycle 2 FAIL → foreman decision, 2026-10-27) ═════
FEES_HTML = """<h2>Registration fees</h2><table><tr><th>Category</th><th>Fee</th></tr>
<tr><td>Member</td><td>£250</td></tr><tr><td>Non-member</td><td>£350</td></tr></table>
<h2>Venue</h2><p>Venue: Royal Hall, Edinburgh</p>"""


def own_row(**kw):
    return cardio_row(booking_url=CARDIO, source_url=CARDIO, **kw)


def _verdicts(res):
    return [(e.get("reason"), e.get("detail"), e.get("identity")) for e in res.evidence if e["step"].startswith("fetch")]


def test_fv4_workshop_sibling_extending_the_title_is_rejected(monkeypatch):
    w = CARDIO + "-workshop"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{w}'>Registration</a></body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({w: f"<html><body><h1>Cardio Update 2027 Workshop</h1>{FEES_HTML}</body></html>"}))
    res = discover(own_row(), page, "", CARDIO)
    assert res.tiers == [] and res.venue_name is None
    assert _verdicts(res) == [("identity_mismatch", "extends_title_with_event_word", "rejected")]


def test_fv4_site_wide_fees_page_naming_the_row_once_is_weak(monkeypatch):
    f = "https://soc.org/fees"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{f}'>Registration fees</a></body></html>"
    body = f"<html><body><p>Cardio Update 2027: see later.</p><p>Neuro Masterclass 2027</p>{FEES_HTML}<a href='/fees/x.pdf'>Fees PDF</a></body></html>"
    net = Net({f: body})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(own_row(), page, "", CARDIO, budget=DiscoveryBudget(max_html=3))
    assert res.tiers == [] and res.venue_name is None and net.fetched == [f]
    assert _verdicts(res) == [("weak_identity", "no_strong_identity", "weak")]


def test_fv4_own_path_registration_page_with_generic_heading_is_strong(monkeypatch):
    r = CARDIO + "/registration"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{r}'>Registration</a></body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({r: f"<html><body><h1>Registration</h1>{FEES_HTML}</body></html>"}))
    res = discover(own_row(), page, "", CARDIO, shell_titles=["Neuro Masterclass 2027"])
    assert sorted(t["price_gbp"] for t in res.tiers) == [250.0, 350.0] and res.city == "Edinburgh"
    assert _verdicts(res)[0][2] == "strong" and res.evidence[1]["detail"] == "own_path"


def test_fv4_heading_equal_to_title_plus_section_word_is_strong(monkeypatch):
    p = "https://soc.org/portal/register?event=991"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{p}'>Register now</a></body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({p: f"<html><body><h1>Cardio Update 2027 — Registration</h1>{FEES_HTML}</body></html>"}))
    res = discover(own_row(), page, "", CARDIO)
    assert sorted(t["price_gbp"] for t in res.tiers) == [250.0, 350.0]
    assert res.evidence[1]["identity"] == "strong" and res.evidence[1]["detail"] == "heading_equals_title"


def test_fv4_other_shell_title_in_a_heading_is_rejected_even_on_own_path(monkeypatch):
    r = CARDIO + "/registration"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{r}'>Registration</a></body></html>"
    body = f"<html><body><h1>Cardio Update 2027</h1><h2>Also this spring: Neuro Masterclass 2027</h2>{FEES_HTML}</body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({r: body}))
    res = discover(own_row(), page, "", CARDIO, shell_titles=["Cardio Update 2027", "Neuro Masterclass 2027"])
    assert res.tiers == [] and res.venue_name is None
    assert _verdicts(res) == [("identity_mismatch", "other_shell_in_heading", "rejected")]


def test_fv4_other_shell_title_in_body_or_nav_only_is_weak(monkeypatch):
    r = CARDIO + "/registration"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{r}'>Registration</a></body></html>"
    body = f"<html><body><nav><a href='/n'>Neuro Masterclass 2027</a></nav><h1>Registration</h1>{FEES_HTML}</body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({r: body}))
    res = discover(own_row(), page, "", CARDIO, shell_titles=["Neuro Masterclass 2027"])
    assert res.tiers == [] and _verdicts(res) == [("weak_identity", "other_shell_in_body", "weak")]


def test_fv4_row_title_inside_a_longer_sibling_title_heading_is_rejected(monkeypatch):
    r = "https://soc.org/events/cardio-update/registration"
    page = f"<html><body><h1>Cardio Update</h1><a href='{r}'>Registration</a></body></html>"
    body = f"<html><body><h1>Cardio Update Advanced</h1>{FEES_HTML}</body></html>"
    monkeypatch.setattr(discovery, "_fetch_html", Net({r: body}))
    rw = row(conference_name="Cardio Update", booking_url="https://soc.org/events/cardio-update")
    res = discover(rw, page, "", "https://soc.org/events/cardio-update", shell_titles=["Cardio Update Advanced"])
    assert res.tiers == [] and _verdicts(res)[0][1] == "other_shell_in_heading"


def test_fv4_shared_fragment_row_is_skipped_entirely(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"followed {u}"))
    res = discover(row(conference_name="ICU Leadership Summit"), SHARED, "", "https://sccm.org/calendar#icu-leadership-summit-ab12")
    assert res.tiers == [] and res.venue_name is None
    assert res.evidence == [{"step": "skip", "reason": "shared_page", "url": "https://sccm.org/calendar#icu-leadership-summit-ab12",
                             "found": [], "elapsed_ms": 0}]


def test_fv4_unlisted_next_event_can_no_longer_leak(monkeypatch):
    html = ("<html><body><h2>ICU Leadership Summit</h2><p>Registration fees</p><p>Member: $400</p>"
            "<h2>Paediatric ICU Day</h2><p>Registration fees</p><p>Delegate: $30</p><p>Student: $45</p></body></html>")
    res = discover(row(conference_name="ICU Leadership Summit"), html, "", "https://sccm.org/calendar#icu", shared=True,
                   shell_titles=["Webinar on Sepsis"])
    assert res.tiers == [] and res.evidence[0]["reason"] == "shared_page"


def test_fv4_agent_hook_skips_a_base_url_shared_by_two_shells(monkeypatch):
    from llm_agent import AgentLoop
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"followed {u}"))
    html = ("<html><body><h2>Annual Meeting 2027</h2><p>Registration fees</p><p>Member: £120</p>"
            "<p>Student: £60</p><h2>Other Webinar 2027</h2><p>Registration fees</p><p>Member: £5</p></body></html>")
    ag = _agent(types.SimpleNamespace(), html=html)
    ag.shells = [{"title": "Annual Meeting 2027", "booking_url": BASE + "?a=1"},
                 {"title": "Other Webinar 2027", "booking_url": BASE + "?a=2"}]
    merged = row(venue_name="V", city="C", abstract_open=True)
    AgentLoop._discover_missing(ag, merged, BASE + "?a=1")
    assert merged["pricing_tiers"] == []
    assert merged["_discovery_evidence"]["evidence"][0]["reason"] == "shared_page"


def test_fv4_agent_hook_passes_every_other_shell_title(monkeypatch):
    from llm_agent import AgentLoop
    seen = {}
    real = discovery.discover

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(discovery, "discover", spy)
    monkeypatch.setattr(discovery, "_fetch_html", Net({}))
    ag = _agent(types.SimpleNamespace())
    ag.shells = [{"title": "Annual Meeting 2027", "booking_url": BASE}, {"title": "Other Webinar 2027", "booking_url": "https://conf.example.org/w"}]
    AgentLoop._discover_missing(ag, row(), BASE)
    assert seen["shell_titles"] == ["Other Webinar 2027"]


def test_fv4_nav_only_title_occurrence_no_longer_matters(monkeypatch):
    p = "https://soc.org/registration-information"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{p}'>Registration</a></body></html>"
    body = (f"<html><body><nav><a href='{CARDIO}'>Cardio Update 2027</a><a>Neuro Masterclass</a></nav>"
            f"<p>1 March 2027</p>{FEES_HTML}</body></html>")
    monkeypatch.setattr(discovery, "_fetch_html", Net({p: body}))
    res = discover(own_row(), page, "", CARDIO)
    assert res.tiers == [] and _verdicts(res) == [("weak_identity", "no_strong_identity", "weak")]


def test_fv4_acronym_row_with_spelled_out_heading_is_weak_not_rejected(monkeypatch):
    a = "https://b-s-h.org.uk/events/asm-2027"
    monkeypatch.setattr(discovery, "_fetch_html", Net({a + "/registration": f"<html><h1>Annual Scientific Meeting 2027 Liverpool</h1>{FEES_HTML}</html>"}))
    rw = row(conference_name="BSH ASM 2027", start_date="2027-04-20", booking_url=a)
    res = discover(rw, f"<html><h1>BSH ASM 2027</h1><a href='{a}/registration'>Registration</a></html>", "", a)
    assert res.tiers == [] and _verdicts(res) == [("weak_identity", "acronym_row", "weak")]


def test_fv4_weak_page_links_and_pdfs_are_not_followed(monkeypatch):
    f = "https://soc.org/fees"
    page = f"<html><body><h1>Cardio Update 2027</h1><a href='{f}'>Registration fees</a></body></html>"
    body = "<html><body><a href='/fees/cardio-update-2027/registration'>Registration</a><a href='/f/fees.pdf'>Registration fees</a></body></html>"
    net = Net({f: body})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(own_row(), page, "", CARDIO, budget=DiscoveryBudget(max_html=3))   # autouse fails any PDF fetch
    assert net.fetched == [f] and res.tiers == []


def test_fv4_hint_strong_only_on_same_or_declared_host(monkeypatch):
    reg = "https://reg.partner.net/cardio-update-2027"
    net = Net({reg: f"<html><body><h1>Delegate rates</h1>{FEES_HTML}</body></html>"})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    res = discover(own_row(), "<html><h1>Cardio Update 2027</h1></html>", "", CARDIO,
                   hints=DiscoveryHints(fees_urls=("https://reg.partner.net/{slug}",)))
    assert len(res.tiers) == 2 and res.evidence[1]["detail"] == "hint"
    net2 = Net({})
    monkeypatch.setattr(discovery, "_fetch_html", net2)
    discover(own_row(), "<html><h1>Cardio Update 2027</h1></html>", "", CARDIO,
             hints=DiscoveryHints(fees_urls=("https://{slug}.evil.net/fees",)))
    assert net2.fetched == []                     # host built from a placeholder: never a hint


def test_fv4_vision_wall_holds_with_two_80s_calls(monkeypatch):
    """Reviewer cycle-2 case: each vision call may take 80 s; the 140 s wall must hold.
    The stub honours the timeout it is given (as the real seam now does via a hard cap)."""
    clk, calls = FakeClock(), []

    def vis(urls, stop_at, timeout=None):
        calls.append(timeout)
        clk.t += 80.0 if timeout is None else min(80.0, timeout)
        return []
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: None)
    monkeypatch.setattr(discovery, "_vision_pricing", vis)
    pimg = "<html><h2>Registration fees</h2>" + "".join(
        f"<img src='/img/fees-table-{i}.png' width='900' height='700' alt='Registration fees table'>" for i in range(4)) + "</html>"
    res = discover({"conference_name": "Wall Test Congress", "event_format": "online", "abstract_open": True},
                   pimg, "", "https://h.org/a/b/c", budget=DiscoveryBudget(clock=clk))
    assert calls and all(c is not None for c in calls)
    assert clk.t <= 140.0 + 1e-9
    assert res.deferred == ["fee_image_pending"]


def test_fv4_vision_seam_passes_the_budget_to_vision(monkeypatch):
    import vision
    got = {}
    monkeypatch.setattr(vision, "extract_pricing_from_images", lambda urls, **k: got.update(k) or [])
    monkeypatch.undo()   # drop the autouse stub of _vision_pricing, keep this one below
    monkeypatch.setattr(vision, "extract_pricing_from_images", lambda urls, **k: got.update(k) or [])
    import time as _t
    discovery._vision_pricing(["https://h.org/x.png"], _t.time() + 30, 30.0)
    assert got["fetch_timeout"] == 30.0 and got["call_timeout"] == 30.0


def test_fv4_vision_module_hard_call_timeout(monkeypatch):
    import time as _t
    import vision
    import safe_fetch
    monkeypatch.setattr(safe_fetch, "enabled", lambda: False)
    fetched = []
    monkeypatch.setattr(vision, "fetch_image_as_data_url", lambda u, timeout=30.0: fetched.append(timeout) or "data:image/png;base64,AA")
    monkeypatch.setattr(vision, "chat_completion", lambda *a, **k: _t.sleep(3.0))
    monkeypatch.setattr(vision, "_client_get", lambda: None)
    t0 = _t.monotonic()
    out = vision.extract_pricing_from_images(["https://h.org/x.png"], stop_at=_t.time() + 10, fetch_timeout=0.7, call_timeout=0.7)
    assert out == [] and _t.monotonic() - t0 < 1.5
    assert fetched and fetched[0] <= 0.7


# ═══ FV4 addendum: total read deadline + size caps on discovery's own fetches ════════════
_REAL_FETCH_HTML, _REAL_FETCH_BYTES = discovery._fetch_html, discovery._fetch_bytes


class _TrickleClient:
    """Stands in for httpx.Client: the body arrives as `chunks`, each after `delays[i]` s.
    Ignores every timeout it is given (a server that keeps the socket alive)."""
    chunks, delays, status = [], [], 200

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def _iter(self):
        import time as _t
        for c, d in zip(type(self).chunks, type(self).delays):
            _t.sleep(d)
            yield c

    def get(self, url):                                      # httpx reads the whole body
        body = b"".join(self._iter())
        return types.SimpleNamespace(status_code=type(self).status, text=body.decode(), content=body,
                                     headers={}, encoding="utf-8")

    def stream(self, method, url):
        cli = self

        class _R:
            status_code, headers, encoding = type(cli).status, {}, "utf-8"
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def raise_for_status(s): pass
            def iter_bytes(s): return cli._iter()
        return _R()


def _trickle(monkeypatch, chunks, delays):
    import httpx
    import safe_fetch
    monkeypatch.setattr(safe_fetch, "enabled", lambda: False)
    monkeypatch.setattr(_TrickleClient, "chunks", chunks)
    monkeypatch.setattr(_TrickleClient, "delays", delays)
    monkeypatch.setattr(httpx, "Client", _TrickleClient)


_PAGE_CHUNK = b"<html><body><h1>Annual Meeting 2027</h1>" + b"<p>Member: \xc2\xa3120</p>" * 20


def test_html_fetch_has_a_total_read_deadline(monkeypatch):
    import time as _t
    _trickle(monkeypatch, [_PAGE_CHUNK] * 12, [0.15] * 12)          # 1.8 s of trickle
    t0 = _t.monotonic()
    out = _REAL_FETCH_HTML("https://conf.example.org/event/annual-2027/registration", 0.6)
    assert out is None and _t.monotonic() - t0 < 1.0


def test_html_fetch_caps_the_body_at_2mb(monkeypatch):
    _trickle(monkeypatch, [b"<p>" + b"x" * 500_000 + b"</p>"] * 5, [0.0] * 5)     # 2.5 MB, fast
    assert _REAL_FETCH_HTML("https://conf.example.org/big", 5.0) is None
    _trickle(monkeypatch, [_PAGE_CHUNK] * 10, [0.0] * 10)        # a real-sized page still comes through
    assert "Annual Meeting 2027" in (_REAL_FETCH_HTML("https://conf.example.org/ok", 5.0) or "")


def test_pdf_fetch_has_a_total_read_deadline_even_on_a_stalled_chunk(monkeypatch):
    import time as _t
    _trickle(monkeypatch, [b"%PDF-1.4 " + b"x" * 1000, b"y" * 1000], [0.0, 1.5])  # 2nd chunk stalls 1.5 s
    t0 = _t.monotonic()
    out = _REAL_FETCH_BYTES("https://conf.example.org/fees.pdf", 0.6)
    assert out is None and _t.monotonic() - t0 < 1.0
    _trickle(monkeypatch, [b"%PDF-1.4 " + b"x" * 1000], [0.0])
    assert _REAL_FETCH_BYTES("https://conf.example.org/fees.pdf", 5.0).startswith(b"%PDF")


# ═══════════════════════════════════════════════════════════════════════════════
# FV6 (V cycle 3): the event's own page and its PDFs get the other-shell checks; the
# identity gate rejects a heading naming another year.
# ═══════════════════════════════════════════════════════════════════════════════
CU = "https://conf.example.org/event/cardio-update-2027/"
SIB = ["Heart Failure Masterclass 2027"]


def cu_row(**kw):
    r = {"conference_name": "Cardio Update 2027", "start_date": "2027-05-01", "event_format": "in_person",
         "pricing_tiers": [], "venue_name": "Hall", "city": "Leeds", "abstract_open": True, "booking_url": CU}
    r.update(kw)
    return r


def _quiet(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: None)
    monkeypatch.setattr(discovery, "_vision_pricing", lambda *a, **k: [])


def _reasons(res):
    return [e.get("reason") for e in res.evidence if e.get("reason")]


def test_fv6_own_page_related_box_with_sibling_heading_gives_nothing(monkeypatch):
    """Reviewer A1: 'Related events / Heart Failure Masterclass 2027 / Registration fees /
    Member £150 / Non-member £220' on the own page wrote the sibling's tiers."""
    _quiet(monkeypatch)
    html = ("<html><body><h1>Cardio Update 2027</h1><p>Details to follow.</p>"
            "<aside><h3>Related events</h3><h4>Heart Failure Masterclass 2027</h4>"
            "<p>Registration fees</p><p>Member £150</p><p>Non-member £220</p></aside></body></html>")
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert res.tiers == []
    assert "own_page_names_other_shell" in _reasons(res)


def test_fv6_own_page_sibling_heading_blocks_images_and_pdfs(monkeypatch):
    """A heading hit takes nothing from the own page: no PDF fetched, no image read."""
    _quiet(monkeypatch)
    monkeypatch.setattr(discovery, "_fee_images", lambda *a, **k: pytest.fail("image scan on a hit page"))
    html = ("<html><body><h1>Cardio Update 2027</h1><h3>Heart Failure Masterclass 2027</h3>"
            '<a href="/files/fees.pdf">Registration fees</a></body></html>')
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)       # _fetch_bytes fails the test if called
    assert res.tiers == [] and "own_page_names_other_shell" in _reasons(res)


def test_fv6_own_page_sibling_in_body_reads_only_text_before_it(monkeypatch):
    _quiet(monkeypatch)
    html = ("<html><body><h1>Cardio Update 2027</h1><h2>Registration fees</h2>"
            "<p>Member £100</p><p>Non-member £140</p>"
            "<div class='related'><p>Heart Failure Masterclass 2027</p><p>Member £150</p>"
            "<p>Non-member £220</p></div></body></html>")
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert sorted(t["price_gbp"] for t in res.tiers) == [100.0, 140.0]
    assert "own_page_sibling_in_body" in _reasons(res)


def test_fv6_own_page_sibling_before_the_fee_heading_skips_the_sweep(monkeypatch):
    _quiet(monkeypatch)
    html = ("<html><body><h1>Cardio Update 2027</h1><p>See also Heart Failure Masterclass 2027.</p>"
            "<h2>Registration fees</h2><p>Member £150</p><p>Non-member £220</p></body></html>")
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert res.tiers == [] and "own_page_sibling_in_body" in _reasons(res)


def test_fv6_own_page_without_siblings_is_unchanged(monkeypatch):
    _quiet(monkeypatch)
    html = ("<html><body><h1>Cardio Update 2027</h1><h2>Registration fees</h2>"
            "<p>Member £100</p><p>Non-member £140</p></body></html>")
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert sorted(t["price_gbp"] for t in res.tiers) == [100.0, 140.0]
    assert _reasons(res) == []


def test_fv6_row_title_inside_a_longer_sibling_in_body_is_located(monkeypatch):
    """Sibling 'Cardio Update 2027 Workshop' contains the row title: it is still cut."""
    _quiet(monkeypatch)
    html = ("<html><body><h1>Cardio Update 2027</h1><h2>Registration fees</h2><p>Member £100</p>"
            "<p>Non-member £140</p><p>Also: Cardio Update 2027 Workshop &mdash; Member £60</p></body></html>")
    res = discover(cu_row(), html, "", CU, shell_titles=["Cardio Update 2027 Workshop"])
    assert sorted(t["price_gbp"] for t in res.tiers) == [100.0, 140.0]


def _pdf_world(monkeypatch, pdf_text):
    _quiet(monkeypatch)
    got = []
    monkeypatch.setattr(discovery, "_fetch_bytes", lambda u, *a, **k: got.append(u) or b"%PDF-1.4")
    monkeypatch.setattr(discovery, "_pdf_text", lambda d, timeout=20.0: pdf_text)
    return got


def test_fv6_sibling_pdf_linked_from_own_page_contributes_nothing(monkeypatch):
    """Reviewer A2: the sibling's '...masterclass-registration.pdf' wrote its tiers."""
    _pdf_world(monkeypatch, "Heart Failure Masterclass 2027\nRegistration fees\nDelegate £300\nTrainee £100\n" + "x" * 50)
    html = ('<html><body><h1>Cardio Update 2027</h1><aside>Also: <a href="/files/heart-failure-masterclass-'
            'registration.pdf">Heart Failure Masterclass registration form</a></aside></body></html>')
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert res.tiers == [] and "pdf_names_other_shell" in _reasons(res)


def test_fv6_pdf_naming_another_year_is_rejected(monkeypatch):
    _pdf_world(monkeypatch, "Cardio Update 2025\nRegistration fees\nDelegate £300\nTrainee £100\n" + "x" * 50)
    html = '<html><body><h1>Cardio Update 2027</h1><a href="/files/fees.pdf">Registration fees</a></body></html>'
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert res.tiers == [] and "pdf_other_year" in _reasons(res)


def test_fv6_own_pdf_with_own_year_still_parses(monkeypatch):
    got = _pdf_world(monkeypatch, "Cardio Update 2027\nRegistration fees\nDelegate £300\nTrainee £100\n" + "x" * 50)
    html = '<html><body><h1>Cardio Update 2027</h1><a href="/files/fees.pdf">Registration fees</a></body></html>'
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert got and sorted(t["price_gbp"] for t in res.tiers) == [100.0, 300.0]


def test_fv6_pdf_in_body_part_after_sibling_is_not_collected(monkeypatch):
    got = _pdf_world(monkeypatch, "Cardio Update 2027\nRegistration fees\nDelegate £300\n" + "x" * 50)
    html = ("<html><body><h1>Cardio Update 2027</h1><p>Related: Heart Failure Masterclass 2027</p>"
            '<a href="/files/fees.pdf">Registration fees</a></body></html>')
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert got == [] and res.tiers == []


def _pid(r, url, html):
    return discovery.page_identity(r, url, html, discovery._to_text(html), own=discovery.own_paths(r))


def test_fv6_h1_equal_title_over_last_years_fee_table_is_rejected():
    """Reviewer A4: h1 = title, fee heading '2026 registration fees' -> was STRONG."""
    html = ("<html><body><h1>Cardio Update 2027</h1><h2>2026 registration fees (for reference)</h2>"
            "<p>Member £90</p><p>Non-member £130</p></body></html>")
    r = cu_row(booking_url="https://conf.example.org/x")
    assert _pid(r, "https://conf.example.org/fees", html) == (discovery.REJECTED, "other_year")


def test_fv6_own_path_past_edition_heading_is_rejected():
    """Reviewer A5: h1 'Cardio Update 2025 Registration' under the 2027 event's path."""
    html = "<html><body><h1>Cardio Update 2025 Registration</h1><p>Member £80</p><p>Student £40</p></body></html>"
    assert _pid(cu_row(), CU + "archive/2025-registration", html) == (discovery.REJECTED, "other_year")


def test_fv6_year_check_allows_start_end_and_title_years():
    r = cu_row(conference_name="Winter Congress 2026", start_date="2026-12-30", end_date="2027-01-02")
    html = "<html><body><h1>Winter Congress 2026</h1><h2>2027 registration fees</h2><p>Member £80</p></body></html>"
    assert _pid(r, CU + "fees", html)[0] == discovery.STRONG
    html2 = "<html><body><h1>Registration</h1><h2>Fees 2027</h2><p>Member £80</p></body></html>"
    assert _pid(cu_row(), CU + "fees", html2) == (discovery.STRONG, "own_path")


def test_fv6_year_in_body_text_only_does_not_reject():
    html = ("<html><body><h1>Registration</h1><h2>Fees</h2><p>Member £80 (early bird until 31 Dec 2026)</p>"
            "</body></html>")
    assert _pid(cu_row(), CU + "fees", html) == (discovery.STRONG, "own_path")


def test_fv6_sibling_in_site_menu_above_h1_does_not_blank_the_page(monkeypatch):
    """Level 2 refinement: a mega-menu listing sibling meetings ABOVE the h1 is excluded from
    the window (window = h1 .. next sibling mention), so the event's own fees still parse."""
    _quiet(monkeypatch)
    html = ("<html><body><nav><a href='/m/hf'>Heart Failure Masterclass 2027</a></nav>"
            "<div class='promo'>Member £999</div>"
            "<h1>Cardio Update 2027</h1><h2>Registration fees</h2><p>Member £100</p><p>Non-member £140</p>"
            "<aside><p>Heart Failure Masterclass 2027</p><p>Member £150</p></aside></body></html>")
    res = discover(cu_row(), html, "", CU, shell_titles=SIB)
    assert sorted(t["price_gbp"] for t in res.tiers) == [100.0, 140.0]
    assert "own_page_sibling_in_body" in _reasons(res)


def test_fv6_sibling_only_in_caller_text_gives_nothing(monkeypatch):
    _quiet(monkeypatch)
    html = ("<html><body><h1>Cardio Update 2027</h1><h2>Registration fees</h2>"
            "<p>Member £100</p><p>Non-member £140</p></body></html>")
    text = "Cardio Update 2027 Registration fees Member £100 Related: Heart Failure Masterclass 2027"
    res = discover(cu_row(), html, text, CU, shell_titles=SIB)
    assert res.tiers == [] and "own_page_sibling_in_body" in _reasons(res)


# ═══════════════════════════════════════════════════════════════════════════════
# FV7: (1) the own-page phrase matcher has no catastrophic backtracking;
#      (2) a prior-year DEADLINE date is not a foreign year.
# ═══════════════════════════════════════════════════════════════════════════════
import subprocess
import sys
from pathlib import Path

_REDOS_INPUTS = {
    "lt_gt_pairs": '"esmo " + "<>" * 10000 + " xyz"',
    "lt_run": '"esmo " + "<" * 50000 + " xyz"',
    "amp_run": '"esmo " + "&" * 20000 + " xyz"',
    "lt_the_run": '"esmo " + "<the " * 5000 + " xyz"',
}


@pytest.mark.parametrize("name", sorted(_REDOS_INPUTS))
def test_fv7_phrase_rx_is_linear_on_adversarial_input(name):
    """Run in a child process with a hard 10 s kill so the pre-fix (exponential) regex fails
    fast instead of hanging the suite; the child reports its own elapsed time."""
    code = ("import time; from extractors.discovery import _phrase_rx\n"
            f"s = {_REDOS_INPUTS[name]}\nrx = _phrase_rx('esmo congress')\n"
            "t = time.perf_counter(); n = sum(1 for _ in rx.finditer(s))\n"
            "print(n, (time.perf_counter() - t) * 1000)")
    try:
        out = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parent),
                             capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{name}: regex still running after 10 s")
    n, ms = out.stdout.split()
    assert int(n) == 0
    assert float(ms) < 100.0, f"{name}: {ms} ms"


@pytest.mark.parametrize("s", ["ESMO&nbsp;<b>Congress</b>", "ESMO - Congress", "ESMO of the Congress", "esmo_congress"])
def test_fv7_phrase_rx_still_matches_separators(s):
    assert discovery._phrase_rx("esmo congress").search(s)


@pytest.mark.parametrize("s", ["esmocongress", "ESMO Congresses"])
def test_fv7_phrase_rx_word_boundaries_unchanged(s):
    assert not discovery._phrase_rx("esmo congress").search(s)


def test_fv7_phrase_rx_tag_and_entity_with_stop_words():
    rx = discovery._phrase_rx("heart failure masterclass 2027")
    assert rx.search("<li>Heart <span class='x'>Failure</span> &amp; the Masterclass&#160;2027</li>")
    assert rx.search("Heart < Failure Masterclass 2027")        # a stray '<' is a separator


X27 = "https://x.org/congress-2027/"


def x_row(**kw):
    r = {"conference_name": "Cardio Congress 2027", "start_date": "2027-04-10", "end_date": "2027-04-12",
         "event_format": "in_person", "pricing_tiers": [], "booking_url": X27}
    r.update(kw)
    return r


def _x_pid(fee_heading, h1="Cardio Congress 2027", r=None):
    html = (f"<html><body><h1>{h1}</h1><h2>{fee_heading}</h2>"
            "<p>Member £300</p><p>Non-member £400</p></body></html>")
    r = r or x_row()
    return discovery.page_identity(r, X27 + "registration", html, discovery._to_text(html),
                                   own=discovery.own_paths(r))


def _pdf_reason(head, r=None):
    run = types.SimpleNamespace(row=r or x_row(), shell_titles=[])
    return discovery._pdf_head_reason(run, head)


def test_fv7_prior_year_early_bird_deadline_in_fee_heading_is_strong():
    assert _x_pid("Early-bird fees (book by 31 December 2026)") == (discovery.STRONG, "own_path")


def test_fv7_prior_year_deadline_in_pdf_head_is_accepted():
    assert _pdf_reason("Registration fees. Bookings before 31 December 2026 receive the early rate. "
                       "Member £300 Non-member £400") is None


@pytest.mark.parametrize("fee_heading,h1", [
    ("2026 registration fees", "Cardio Congress 2027"),
    ("Registration fees", "Cardio Update 2025 Registration"),
    ("Early-bird fees (book by 31 December 2025)", "Cardio Congress 2027"),   # two years back
    ("Early bird fees for Cardio Update 2026", "Cardio Congress 2027"),       # no date: an edition, not a deadline
])
def test_fv7_other_years_still_rejected(fee_heading, h1):
    assert _x_pid(fee_heading, h1) == (discovery.REJECTED, "other_year")


def test_fv7_pdf_two_years_back_deadline_still_rejected():
    assert _pdf_reason("Early-bird deadline 1 March 2025. Member £300") == "pdf_other_year"


def test_fv7_prior_year_without_deadline_word_still_rejected_in_pdf():
    assert _pdf_reason("Cardio Congress 2026 registration fees. Member £300") == "pdf_other_year"
