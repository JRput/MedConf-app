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
    monkeypatch.setattr(discovery, "_pdf_text", lambda d: "Registration fees\nDelegate £200\nStudent £90\n" + "x" * 50)
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
    monkeypatch.setattr(discovery, "_vision_pricing", lambda urls, stop_at: seen.append(urls) or [
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
    monkeypatch.setattr(discovery, "_vision_pricing", lambda urls, stop_at: got.append(urls[0][:21]) or [
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
    assert res2.tiers == [] and any("identity_mismatch" in e["found"] for e in res2.evidence)


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
    home = '<html><body><a href="/scientific-programme/abstracts/">Abstract Submission</a> Welcome to the Zebrafish Symposium</body></html>'
    abs_ = ("<html><body><h1>Zebrafish Symposium 2027 abstracts</h1>"
            "<p>Abstract submission deadline: 1 August 2099. Submit your abstract.</p></body></html>")
    net = Net({org: home, "https://emuc.example.net/scientific-programme/abstracts/": abs_})
    monkeypatch.setattr(discovery, "_fetch_html", net)
    r = row(pricing_tiers=[{"a": 1}], event_format="online", organiser_url=org,
            conference_name="Zebrafish Symposium 2027")
    res = discover(r, "<html><body>stub</body></html>", "", BASE)
    assert res.abstract_deadline == "2099-08-01" and len(net.fetched) == 2


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
    page = f'<html><head><script type="application/ld+json">{ld}</script></head><body>Zebrafish Symposium 2027</body></html>'
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
