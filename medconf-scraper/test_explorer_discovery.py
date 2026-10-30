"""X2 explorer-discovery: shared nightly discovery of fee / abstract / venue
sub-pages (mission "cross-source coverage", ticket X2)."""
import json
import pytest

from remediator import explorer
from remediator.explorer import (
    AuditTrail, ExploreBudget, find_registration_links, find_same_domain_anchors,
    find_external_event_links, llm_classify_anchors, prioritise_nav_links,
    static_nav_links, TICKETING_HOST_RE, EXPLORERS,
)

BASE = "https://www.soc.org/events/2027/annual-meeting"
ROW = {"id": 1, "conference_name": "Society Annual Meeting 2027", "start_date": "2027-05-10",
       "source_url": BASE}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    explorer.reset_fetch_state()
    monkeypatch.setattr(explorer, "render_page", lambda url: (None, None, []))
    yield
    explorer.reset_fetch_state()


def fake_pages(monkeypatch, pages: dict):
    """Route every explorer fetch to `pages` {url: html}; records fetched urls."""
    import re, html as _h
    calls = []

    def fetch(url, **kw):
        calls.append(url)
        h = pages.get(url)
        if h is None:
            return None, None
        t = _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))).strip()
        return t, h
    monkeypatch.setattr(explorer, "fetch_page_text_and_html", fetch)
    return calls


# ---------------------------------------------------------------- 2. link wording
@pytest.mark.parametrize("text", [
    "Delegate information", "Delegate rates", "Delegate fees", "Attend", "Attending",
    "Costs", "Prices", "Pricing", "Tickets", "Book", "Booking", "Rates",
    "Inscripción", "Inscription", "Anmeldung", "Registrierung", "Tarifs", "Kosten",
    "Gebühren", "Iscrizione", "Quote", "Preise", "Inschrijving", "Tarieven",
])
def test_registration_link_wording(text):
    html = f'<a href="/events/2027/annual-meeting/x1">{text}</a>'
    got = find_registration_links(html, BASE)
    assert [u for u, _ in got] == ["https://www.soc.org/events/2027/annual-meeting/x1"], text


@pytest.mark.parametrize("text", ["Newsletter subscribe", "Log in", "Sign in to book", "Privacy", "Cookie rates"])
def test_registration_link_negatives_unchanged(text):
    assert find_registration_links(f'<a href="/x1">{text}</a>', BASE) == []


# ---------------------------------------------------------------- 3. query strings kept
def test_query_strings_kept_in_registration_links():
    html = ('<a href="/register.aspx?eventid=55#top">Register</a>'
            '<a href="/register.aspx?eventid=56">Register</a>')
    got = [u for u, _ in find_registration_links(html, BASE)]
    assert got == ["https://www.soc.org/register.aspx?eventid=55",
                   "https://www.soc.org/register.aspx?eventid=56"]


def test_fragment_still_dropped_and_deduped():
    html = '<a href="/fees#a">Fees</a><a href="/fees#b">Fees</a>'
    assert [u for u, _ in find_registration_links(html, BASE)] == ["https://www.soc.org/fees"]


def test_same_domain_anchors_keep_query_and_single_quotes():
    html = "<a href='/events/x/fees?id=7#t'>Fees</a>"
    assert find_same_domain_anchors(html, BASE) == ["https://www.soc.org/events/x/fees?id=7"]


def test_llm_classify_anchors_keeps_query():
    html = '<a href="/page.aspx?id=5">Delegate area</a>'
    got = llm_classify_anchors(html=html, base_url=BASE, field="fees", event_title="X",
                               llm_call=lambda p: "https://www.soc.org/page.aspx?id=5")
    assert got == ["https://www.soc.org/page.aspx?id=5"]


# ---------------------------------------------------------------- 4. nav
def _nav(items):
    return "<nav>" + "".join(f'<a href="/am27/{i.lower()}">{i}</a>' for i in items) + "</nav>"


def test_nav_registration_in_tenth_position_is_found():
    items = ["About", "Membership", "Education", "Journal", "Events", "Policy", "Careers",
             "Shop", "Awards", "Registration", "Programme", "Abstracts"]
    picks = prioritise_nav_links(static_nav_links(_nav(items), BASE), BASE)
    assert picks[0][1] == "Registration" and picks[0][2] == "fees"
    assert any(k == "abstract" for _, _, k in picks)


def test_nav_ranks_fee_words_first_even_beyond_24_links():
    items = [f"Topic{i}" for i in range(40)] + ["Registration"]
    picks = prioritise_nav_links(static_nav_links(_nav(items), BASE), BASE)
    assert picks and picks[0][1] == "Registration"


def test_nav_max_links_is_24():
    assert explorer.NAV_MAX_LINKS == 24


FEE_PAGE = ("<html><body><h1>Society Annual Meeting 2027</h1><h2>Registration fees</h2>"
            "<p>Member £120</p><p>Non-member £200</p><p>Student £60</p></body></html>")


def test_unflagged_source_walks_nav_with_reduced_allowance(monkeypatch):
    base = "https://www.soc.org/events/2027/congress"   # no fee word / "annual" in any href
    home = ('<html><body><nav><a href="/events/2027/congress/info">General Info</a>'
            '<a href="/events/2027/congress/venue">Venue</a><a href="/events/2027/congress/x">Delegates</a></nav>'
            '<p>Society Annual Meeting 2027</p></body></html>')
    calls = fake_pages(monkeypatch, {base: home,
                                     "https://www.soc.org/events/2027/congress/info": FEE_PAGE})
    row = {**ROW, "source_url": base}  # NOT flagged detail_is_multipage
    res = explorer.explore_for_pricing(row=row, page_text="Society Annual Meeting 2027",
                                       page_html=home, base_url=base, llm_call=lambda p: None)
    assert res.found, res.audit_trail.notes
    assert any(str(n).startswith("nav_page_followed:") for n in res.audit_trail.notes)
    assert any("nav_walk_unflagged" in str(n) for n in res.audit_trail.notes)


def test_unflagged_nav_walk_never_exceeds_two_fetches(monkeypatch):
    base = "https://www.soc.org/events/2027/congress"
    nav = "".join(f'<a href="/events/2027/congress/p{i}">Information {i}</a>' for i in range(6))
    home = f"<html><body><nav>{nav}</nav><p>Society Annual Meeting 2027</p></body></html>"
    pages = {base: home}
    for i in range(6):
        pages[f"https://www.soc.org/events/2027/congress/p{i}"] = "<html><body>Society Annual Meeting 2027 nothing</body></html>"
    calls = fake_pages(monkeypatch, pages)
    row = {**ROW, "source_url": base}
    explorer.explore_for_pricing(row=row, page_text="Society Annual Meeting 2027", page_html=home,
                                 base_url=base, llm_call=lambda p: None)
    assert len([c for c in calls if c.rsplit("/", 1)[-1] in {f"p{i}" for i in range(6)}]) <= 2


def test_unflagged_nav_walk_needs_a_discovery_word():
    html = '<nav><a href="/a/shop">Shop</a><a href="/a/awards">Awards</a></nav>'
    assert explorer.nav_has_discovery_words(html, BASE) is False
    assert explorer.nav_has_discovery_words(_nav(["Programme", "Venue"]), BASE) is True


# ---------------------------------------------------------------- 5. host lists
@pytest.mark.parametrize("host", ["confex.com", "dropbox.com", "box.com", "docs.google.com", "regonline.com"])
def test_legit_hosts_not_junk(host):
    assert not explorer.is_junk_external(f"https://{host}/forms/d/abc" if "google" in host else f"https://{host}/x")


@pytest.mark.parametrize("url", ["https://x.com/soc", "https://twitter.com/soc", "https://www.facebook.com/soc",
                                 "https://uk.linkedin.com/in/x", "https://www.instagram.com/soc",
                                 "https://www.youtube.com/watch?v=1", "https://www.google.com/",
                                 "https://www.google.com/search?q=x", "https://m.x.com/a"])
def test_real_junk_still_blocked(url):
    assert explorer.is_junk_external(url)


def test_google_forms_is_not_junk_but_google_home_is():
    assert not explorer.is_junk_external("https://docs.google.com/forms/d/e/abc/viewform")
    assert explorer.is_junk_external("https://docs.google.com/")


def test_external_links_confex_and_google_form_followed():
    html = ('<p>Registration</p><a href="https://confex.com/am27">Register now</a>'
            '<a href="https://docs.google.com/forms/d/x">Book now</a>'
            '<a href="https://x.com/soc">Register</a>')
    urls = [u for u, _ in find_external_event_links(html, BASE)]
    assert "https://confex.com/am27" in urls
    assert "https://docs.google.com/forms/d/x" in urls
    assert "https://x.com/soc" not in urls


@pytest.mark.parametrize("host", ["exordo.com", "app.exordo.com", "eventsforce.net", "conftool.pro", "whova.com",
                                  "ti.to", "eventscase.com", "bizzabo.com", "hopin.com", "cvent.com",
                                  "regonline.com", "eventbrite.co.uk", "ticketsource.co.uk",
                                  "tickettailor.com", "trybooking.com", "humanitix.com"])
def test_ticketing_hosts(host):
    assert TICKETING_HOST_RE.search(host), host


def test_ti_to_does_not_match_arbitrary_hosts():
    assert not TICKETING_HOST_RE.search("dentistry.ti.tool.org")


# ---------------------------------------------------------------- 6. ticketing hosts
def _ld(offers, name="Society Annual Meeting 2027", start="2027-05-10"):
    return ('<html><head><title>%s tickets</title><script type="application/ld+json">%s</script></head>'
            '<body>%s</body></html>' % (name, json.dumps({"@context": "https://schema.org", "@type": "Event",
                                                           "name": name, "startDate": start, "offers": offers}),
                                        name))


def test_ticketing_jsonld_offers():
    html = _ld([{"@type": "Offer", "name": "Member", "price": "120.00", "priceCurrency": "GBP"},
                {"@type": "Offer", "name": "Non-member", "price": "200", "priceCurrency": "GBP"}])
    tiers = explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027", html, AuditTrail())
    assert [(t["tier_label"], t["price_gbp"], t["currency"]) for t in tiers] == [
        ("Member", 120.0, "GBP"), ("Non-member", 200.0, "GBP")]


def test_ticketing_aggregate_offer_low_high():
    html = _ld({"@type": "AggregateOffer", "lowPrice": "50", "highPrice": "150", "priceCurrency": "EUR"})
    tiers = explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027", html, AuditTrail())
    assert sorted(t["price_gbp"] for t in tiers) == [50.0, 150.0]
    assert {t["currency"] for t in tiers} == {"EUR"}


def test_ticketing_drops_holding_fee_deposit_refundable():
    html = _ld([{"@type": "Offer", "name": "Holding fee (fully refunded)", "price": "10", "priceCurrency": "GBP"},
                {"@type": "Offer", "name": "Deposit", "price": "25", "priceCurrency": "GBP"},
                {"@type": "Offer", "name": "Refundable place", "price": "30", "priceCurrency": "GBP"},
                {"@type": "Offer", "name": "Delegate", "price": "95", "priceCurrency": "GBP"}])
    tiers = explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027", html, AuditTrail())
    assert [t["tier_label"] for t in tiers] == ["Delegate"]


def test_ticketing_currency_never_defaulted():
    html = _ld([{"@type": "Offer", "name": "Delegate", "price": "95"}])
    assert explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027", html, AuditTrail()) == []


def test_ticketing_other_event_offers_ignored():
    html = _ld([{"@type": "Offer", "name": "Ticket", "price": "40", "priceCurrency": "GBP"}],
               name="Totally Different Surgical Symposium", start="2027-09-01")
    assert explorer.ticketing_host_tiers(ROW, "Totally Different Surgical Symposium", html, AuditTrail()) == []


def test_ticketing_wrong_date_same_title_rejected():
    html = _ld([{"@type": "Offer", "name": "Ticket", "price": "40", "priceCurrency": "GBP"}], start="2026-05-10")
    assert explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027", html, AuditTrail()) == []


def test_ticketing_eventbrite_inline_ticket_data():
    data = {"ticket_classes": [
        {"display_name": "Standard", "cost": {"currency": "GBP", "major_value": "45.00", "display": "£45.00"}},
        {"display_name": "Student", "cost": {"currency": "GBP", "major_value": "20.00", "display": "£20.00"}}]}
    html = ("<html><head><title>Society Annual Meeting 2027 Tickets</title></head><body>Society Annual Meeting 2027"
            "<script>window.__SERVER_DATA__ = %s;</script></body></html>" % json.dumps(data))
    tiers = explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027", html, AuditTrail())
    assert [(t["tier_label"], t["price_gbp"]) for t in tiers] == [("Standard", 45.0), ("Student", 20.0)]


def test_ticketing_rendered_text_drops_holding_fee_sentence():
    text = ("Society Annual Meeting 2027. Member ticket - £120 Non-member ticket - £200 "
            "A £10 holding fee is taken at booking and is fully refunded on attendance.")
    tiers = explorer.ticketing_host_tiers(ROW, text, "<html><body>" + text + "</body></html>", AuditTrail())
    assert tiers and all(t["price_gbp"] != 10.0 for t in tiers)


def test_pricing_follows_eventbrite_link_and_reads_offers(monkeypatch):
    eb = "https://www.eventbrite.co.uk/e/society-annual-meeting-2027-tickets-123"
    main = f'<html><body><p>Society Annual Meeting 2027</p><a href="{eb}">Book</a></body></html>'
    calls = fake_pages(monkeypatch, {BASE: main, eb: _ld([
        {"@type": "Offer", "name": "Delegate", "price": "95", "priceCurrency": "GBP"},
        {"@type": "Offer", "name": "Holding fee", "price": "10", "priceCurrency": "GBP"}])})
    # provenance: a ticketing page is eligible only when it IS the row's booking_url / organiser_url
    res = explorer.explore_for_pricing(row={**ROW, "booking_url": eb}, page_text="Society Annual Meeting 2027",
                                       page_html=main, base_url=BASE, llm_call=lambda p: None)
    assert res.found and res.method.startswith("ticketing_jsonld"), (res.method, res.audit_trail.notes)
    assert [t["price_gbp"] for t in res.value] == [95.0]
    assert res.external_url == eb
    assert (res.evidence_url, res.evidence_identity) == (eb, "strong")


# ---------------------------------------------------------------- 7. LLM sees sub-pages
def test_llm_final_step_sees_subpage_text(monkeypatch):
    reg = "https://www.soc.org/events/2027/annual-meeting/registration"
    main = '<html><body><p>Society Annual Meeting 2027</p><a href="%s">Registration</a></body></html>' % reg
    sub = ("<html><body><h1>Society Annual Meeting 2027</h1>"
           "<p>Delegates pay one hundred and twenty pounds for members.</p></body></html>")
    fake_pages(monkeypatch, {BASE: main, reg: sub})
    seen = []
    explorer.explore_for_pricing(row=ROW, page_text="Society Annual Meeting 2027", page_html=main,
                                 base_url=BASE, llm_call=lambda p: seen.append(p) or None)
    assert any("one hundred and twenty pounds" in p for p in seen)


def test_llm_subpage_text_is_capped(monkeypatch):
    regs = [f"https://www.soc.org/events/2027/annual-meeting/registration{i}" for i in range(3)]
    main = ('<html><body><p>Society Annual Meeting 2027</p>'
            + "".join(f'<a href="{u}">Registration {i}</a>' for i, u in enumerate(regs)) + "</body></html>")
    pages = {BASE: main}
    for i, u in enumerate(regs):
        pages[u] = ("<html><body><p>Society Annual Meeting 2027 MARK%d </p><p>%s</p></body></html>"
                    % (i, ("filler words here " * 2000)))
    fake_pages(monkeypatch, pages)
    seen = []
    explorer.explore_for_pricing(row=ROW, page_text="Society Annual Meeting 2027", page_html=main,
                                 base_url=BASE, llm_call=lambda p: seen.append(p) or None)
    final = [p for p in seen if "REGISTRATION FEES" in p][-1]
    body = final.split("PAGE TEXT:")[1]
    assert "MARK0" in body and "MARK1" in body
    assert len(body) <= 8000 + 20000 + 600  # main page cap + sub-page cap + separators
    assert body.count("filler words here") * len("filler words here ") <= 20000 + 200


# ---------------------------------------------------------------- 8. abstracts
def _stub_abstract_fixer(monkeypatch):
    import remediator.fixers.abstract as fa
    monkeypatch.setattr(fa, "fix_abstract_status",
                        lambda row, text, llm: ({"abstract_open": True, "abstract_deadline": "2027-02-01"}, "stub")
                        if "papers" in text.lower() and "2027-02-01" in text else (None, None))


def test_call_for_papers_page_without_word_abstract_is_accepted(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    cfp = "https://www.soc.org/events/2027/annual-meeting/cfp"
    main = '<html><body><p>Society Annual Meeting 2027</p><a href="/events/2027/annual-meeting/cfp">Call for papers</a></body></html>'
    fake_pages(monkeypatch, {BASE: main, cfp: "<html><body>Call for papers closes 2027-02-01</body></html>"})
    res = explorer.explore_for_abstract_status(row=ROW, page_text="Society Annual Meeting 2027", page_html=main,
                                               base_url=BASE, llm_call=lambda p: None)
    assert res.found and res.value["abstract_deadline"] == "2027-02-01"
    assert cfp in res.audit_trail.subpages_fetched


def test_nav_only_abstracts_link_is_followed(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    url = "https://www.soc.org/events/2027/annual-meeting/p7"
    main = ('<html><body><nav><a href="/events/2027/annual-meeting/p7">Abstracts</a></nav>'
            '<p>Society Annual Meeting 2027</p></body></html>')
    fake_pages(monkeypatch, {BASE: main, url: "<html><body>Call for papers closes 2027-02-01. abstracts</body></html>"})
    res = explorer.explore_for_abstract_status(row=ROW, page_text="Society Annual Meeting 2027", page_html=main,
                                               base_url=BASE, llm_call=lambda p: None)
    assert res.found and url in res.audit_trail.subpages_fetched


def test_unreached_abstract_page_returns_unknown_not_closed(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    main = ('<html><body><p>Society Annual Meeting 2027</p>'
            '<a href="/events/2027/annual-meeting/abstracts-info">Abstracts</a></body></html>')
    fake_pages(monkeypatch, {BASE: main})  # sub-page fetch fails
    res = explorer.explore_for_abstract_status(row=ROW, page_text="Society Annual Meeting 2027", page_html=main,
                                               base_url=BASE, llm_call=lambda p: None)
    assert not res.found and res.value is None
    assert res.method == "unknown_unreached"


def test_unreached_pdf_abstract_link_returns_unknown(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    main = ('<html><body><p>Society Annual Meeting 2027</p>'
            '<a href="/files/call-for-abstracts.pdf">Call for abstracts</a></body></html>')
    fake_pages(monkeypatch, {BASE: main})
    monkeypatch.setattr(explorer, "_fetch_document_text", lambda url, trail: None)
    res = explorer.explore_for_abstract_status(row=ROW, page_text="Society Annual Meeting 2027", page_html=main,
                                               base_url=BASE, llm_call=lambda p: None)
    assert not res.found and res.method == "unknown_unreached"


def test_no_abstract_links_anywhere_still_closed(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    main = '<html><body><p>Society Annual Meeting 2027 CPD study day</p></body></html>'
    fake_pages(monkeypatch, {BASE: main})
    res = explorer.explore_for_abstract_status(row=ROW, page_text="Society Annual Meeting 2027 CPD study day",
                                               page_html=main, base_url=BASE, llm_call=lambda p: None)
    assert res.found and res.value == {"abstract_open": False}


def test_no_html_at_all_is_unknown_not_closed(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    res = explorer.explore_for_abstract_status(row=ROW, page_text="Society Annual Meeting 2027", page_html=None,
                                               base_url=BASE, llm_call=lambda p: None)
    assert not res.found


# ---------------------------------------------------------------- 1. venue explorer
def _place(html, base=BASE):
    return explorer.extract_place_from_html(html, base)


def test_maps_embed_q_param():
    h = ('<iframe src="https://maps.google.com/maps?q=Royal%20College%20of%20Physicians%2C%2011%20St%20Andrews%20'
         'Place%2C%20London%20NW1%204LE&output=embed"></iframe>')
    p = _place(h)
    assert p["venue_name"] == "Royal College of Physicians" and p["city"] == "London"


def test_maps_embed_google_com_maps_embed_q():
    h = '<iframe src="https://www.google.com/maps/embed?pb=!1m18&q=Hilton+Garden+Inn,+Dublin"></iframe>'
    p = _place(h)
    assert p["venue_name"] == "Hilton Garden Inn" and p["city"] == "Dublin"


def test_maps_place_path():
    h = '<a href="https://www.google.com/maps/place/Messe+Berlin/@52.5,13.2,15z">Map</a>'
    assert _place(h)["venue_name"] == "Messe Berlin"


def test_maps_coordinates_only_ignored():
    assert _place('<iframe src="https://maps.google.com/maps?q=52.5,13.2&output=embed"></iframe>') is None


def test_maps_embed_in_footer_ignored():
    h = ('<html><body><p>Hello</p><footer><iframe src="https://maps.google.com/maps?q=Head%20Office%2C%2020%20Park'
         '%20Crescent%2C%20London"></iframe></footer></body></html>')
    assert _place(h) is None


def test_jsonld_location():
    ld = {"@type": "Event", "location": {"@type": "Place", "name": "ExCeL London",
                                         "address": {"@type": "PostalAddress", "addressLocality": "London"}}}
    h = '<script type="application/ld+json">%s</script>' % json.dumps(ld)
    p = _place(h)
    assert p["venue_name"] == "ExCeL London" and p["city"] == "London"


def test_labelled_venue_line():
    p = _place("<html><body><p>Venue: Manchester Central Convention Complex, Manchester</p></body></html>")
    assert p["venue_name"].startswith("Manchester Central") and p["city"] == "Manchester"


def test_address_block_us():
    p = _place("<html><body><div>Sheraton Grand Chicago Riverwalk</div><p>301 East North Water Street, Chicago, IL 60611</p></body></html>")
    assert p and p["city"] == "Chicago"


def test_footer_head_office_address_never_returned():
    h = ("<html><body><p>Welcome to the meeting.</p><footer><p>Venue: Head Office</p>"
         "<p>Royal Society of Things, 20 Park Crescent, London W1B 1AE</p></footer></body></html>")
    assert _place(h) is None


def test_office_phone_text_rejected():
    assert _place("<html><body><p>Location: Office: 020 7935 1174 Tel +44 20 7935 1174</p></body></html>") is None


def _trail():
    return AuditTrail()


def test_venue_explorer_follows_travel_page(monkeypatch):
    t = "https://www.soc.org/events/2027/annual-meeting/travel"
    main = '<html><body><p>Society Annual Meeting 2027</p><a href="/events/2027/annual-meeting/travel">Getting there</a></body></html>'
    calls = fake_pages(monkeypatch, {BASE: main, t: "<html><body><h1>Society Annual Meeting 2027 travel</h1>"
                                     "<p>Venue: Manchester Central, Manchester</p></body></html>"})
    tr = _trail()
    got = explorer.explore_for_venue(ROW, main, BASE, tr)
    assert got and got["venue_name"].startswith("Manchester Central") and got["url"] == t
    assert t in tr.subpages_fetched
    assert any("venue_page_followed" in str(n) for n in tr.notes)


@pytest.mark.parametrize("text,path", [
    ("Venue", "v"), ("Location", "l"), ("Travel", "t"), ("Getting there", "g"), ("How to find us", "h"),
    ("Directions", "d"), ("Accommodation", "a"), ("Hotels", "ho"), ("Map", "m"),
])
def test_venue_link_wording(text, path):
    html = f'<a href="/events/2027/annual-meeting/{path}">{text}</a>'
    got = explorer.find_venue_links(html, BASE)
    assert [u for u, _ in got] == [f"https://www.soc.org/events/2027/annual-meeting/{path}"]


def test_venue_link_matches_on_url():
    got = explorer.find_venue_links('<a href="/events/2027/annual-meeting/venue-and-travel">More</a>', BASE)
    assert got


def test_venue_explorer_max_three_pages(monkeypatch):
    links = "".join(f'<a href="/events/2027/annual-meeting/venue{i}">Venue {i}</a>' for i in range(6))
    main = f"<html><body><p>Society Annual Meeting 2027</p>{links}</body></html>"
    pages = {BASE: main}
    for i in range(6):
        pages[f"https://www.soc.org/events/2027/annual-meeting/venue{i}"] = "<html><body>nothing here</body></html>"
    calls = fake_pages(monkeypatch, pages)
    assert explorer.explore_for_venue(ROW, main, BASE, _trail()) is None
    assert len([c for c in calls if c != BASE]) <= 3


def test_venue_explorer_head_office_find_us_page_outside_event_path_rejected(monkeypatch):
    t = "https://www.soc.org/about/how-to-find-us"
    main = '<html><body><p>Meeting</p><a href="/about/how-to-find-us">How to find us</a></body></html>'
    fake_pages(monkeypatch, {BASE: main, t: "<html><body>Our office: Royal Society, 20 Park Crescent, London W1B 1AE. "
                                            "Venue: Head Office, London</body></html>"})
    assert explorer.explore_for_venue(ROW, main, BASE, _trail()) is None


def test_venue_explorer_one_external_organiser_hop(monkeypatch):
    org = "https://congress.example.org/am27"
    main = "<html><body><p>Society Annual Meeting 2027</p></body></html>"
    calls = fake_pages(monkeypatch, {BASE: main, org: "<html><body><h1>Society Annual Meeting 2027</h1>"
                                                      "<p>Venue: Palais des Congres, Paris</p></body></html>"})
    row = {**ROW, "organiser_url": org}
    tr = _trail()
    got = explorer.explore_for_venue(row, main, BASE, tr)
    assert got and got["venue_name"].startswith("Palais des Congres") and got["url"] == org
    assert any("venue_external_followed" in str(n) for n in tr.notes)


def test_venue_external_hop_identity_gate(monkeypatch):
    org = "https://other.example.org/x"
    main = "<html><body><p>Society Annual Meeting 2027</p></body></html>"
    fake_pages(monkeypatch, {BASE: main, org: "<html><body><p>Venue: Some Other Hotel, Rome</p></body></html>"})
    assert explorer.explore_for_venue({**ROW, "organiser_url": org}, main, BASE, _trail()) is None


def test_venue_explorer_registered_for_runner(monkeypatch):
    assert "venue_name" in EXPLORERS and "city" in EXPLORERS
    t = "https://www.soc.org/events/2027/annual-meeting/venue"
    main = '<html><body><p>Society Annual Meeting 2027</p><a href="/events/2027/annual-meeting/venue">Venue</a></body></html>'
    fake_pages(monkeypatch, {BASE: main, t: "<html><body>Society Annual Meeting 2027 "
                                            "<p>Venue: ExCeL London, London</p></body></html>"})
    kw = dict(row=ROW, page_text="Society Annual Meeting 2027", page_html=main, base_url=BASE, llm_call=lambda p: None)
    v = EXPLORERS["venue_name"](**kw)
    c = EXPLORERS["city"](**kw)
    assert v.found and v.value.startswith("ExCeL London") and v.field == "venue_name"
    assert c.found and c.value == "London" and c.field == "city"


def test_fix_venue_uses_page_html_evidence_without_network():
    from remediator.fixers.venue import fix_venue, fix_city
    html = '<iframe src="https://maps.google.com/maps?q=Hilton+Garden+Inn,+Dublin&output=embed"></iframe>'
    row = {**ROW, "_page_html": html}
    assert fix_venue(row, "Society Annual Meeting 2027 programme", lambda p: None)[0] == "Hilton Garden Inn"
    assert fix_city(row, "Society Annual Meeting 2027 programme", lambda p: None)[0] == "Dublin"


# ---------------------------------------------------------------- live-proof regressions
def test_ticketing_offer_equal_to_named_holding_fee_is_dropped():
    """RCPath 'The Consultant Files': the Eventbrite AggregateOffer (10.0 GBP) is the
    refundable holding fee the page text describes, not a registration fee."""
    html = _ld({"@type": "AggregateOffer", "lowPrice": "10.0", "highPrice": "10.0", "priceCurrency": "GBP"})
    text = ("Society Annual Meeting 2027. Please note that a £10 holding fee is charged at registration. "
            "This will be fully refunded when you attend the event.")
    assert explorer.ticketing_host_tiers(ROW, text, html, AuditTrail()) == []


def test_ticketing_offer_kept_when_page_has_no_holding_fee_wording():
    html = _ld({"@type": "AggregateOffer", "lowPrice": "10.0", "highPrice": "10.0", "priceCurrency": "GBP"})
    tiers = explorer.ticketing_host_tiers(ROW, "Society Annual Meeting 2027 tickets £10", html, AuditTrail())
    assert [t["price_gbp"] for t in tiers] == [10.0]


@pytest.mark.parametrize("line,city", [("Berlin, Germany", "Berlin"), ("Madrid, Spain", "Madrid")])
def test_city_country_location_line_is_a_city_not_a_venue(line, city):
    p = _place(f"<html><body><p>Location: {line}</p></body></html>")
    assert p["venue_name"] is None and p["city"] == city


def test_abstract_explorer_follows_organiser_site(monkeypatch):
    import remediator.fixers.abstract as fa
    org = "https://congress.example.org/am27/"
    ab = "https://congress.example.org/am27/abstracts/"
    monkeypatch.setattr(fa, "fix_abstract_status",
                        lambda row, text, llm: ({"abstract_open": True, "abstract_deadline": "2027-08-01"}, "stub")
                        if "deadline of 1 August" in text else ({"abstract_open": False}, "no_abstract_mention")
                        if "abstract" not in text.lower() else (None, None))
    main = "<html><body><p>Society Annual Meeting 2027 stub</p></body></html>"
    fake_pages(monkeypatch, {BASE: main,
                             org: '<html><body>Society Annual Meeting 2027 <a href="/am27/abstracts/">Abstracts</a></body></html>',
                             ab: "<html><body>Society Annual Meeting 2027 abstracts: regular submission deadline of 1 August</body></html>"})
    res = explorer.explore_for_abstract_status(row={**ROW, "organiser_url": org}, page_text="Society Annual Meeting 2027 stub",
                                               page_html=main, base_url=BASE, llm_call=lambda p: None)
    # provenance: the organiser_url path counts as an own path, so its sub-page is STRONG
    assert res.found and res.value["abstract_deadline"] == "2027-08-01"
    assert res.external_url == ab
    assert (res.evidence_url, res.evidence_identity) == (ab, "strong")


def test_main_no_abstract_mention_is_not_final_when_organiser_unreachable(monkeypatch):
    import remediator.fixers.abstract as fa
    monkeypatch.setattr(fa, "fix_abstract_status", lambda row, text, llm: ({"abstract_open": False}, "no_abstract_mention"))
    main = "<html><body><p>Society Annual Meeting 2027 stub</p></body></html>"
    fake_pages(monkeypatch, {BASE: main})   # organiser fetch fails
    res = explorer.explore_for_abstract_status(
        row={**ROW, "organiser_url": "https://congress.example.org/"}, page_text="Society Annual Meeting 2027 stub",
        page_html=main, base_url=BASE, llm_call=lambda p: None)
    assert not res.found and res.method == "unknown_unreached"
