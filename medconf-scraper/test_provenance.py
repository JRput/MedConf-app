"""Field provenance: every pricing tier / venue / abstract write carries the page it came from
and how sure we are it is this event's (own_page | strong); anything else is refused.

Offline: supabase, fetches, PDF and vision seams are stubbed."""
import html as _h
import logging
import re
import types
from types import SimpleNamespace

import pytest

import database
from extractors import discovery
from extractors.discovery import apply_to_row, discover
from remediator import explorer, runner
from remediator.explorer import AuditTrail, EXPLORERS, ExploreBudget, ExploreResult

OWN = "https://e.org/x"


# ======================================================================
# 1. database.insert_pricing_tiers
# ======================================================================
class _FakeSB:
    def __init__(self):
        self.rows, self.calls = None, 0

    def table(self, name):
        assert name == "pricing_tiers"
        return self

    def insert(self, rows):
        self.rows, self.calls = rows, self.calls + 1
        return self

    def execute(self):
        return None


def _t(label="Member", price=100.0, **kw):
    t = {"tier_label": label, "price_gbp": price, "currency": "GBP"}
    t.update(kw)
    return t


def _ev(**kw):
    return {"evidence_url": OWN, "evidence_identity": "own_page", **kw}


def test_insert_accepts_provenance_and_stamps_scraper(monkeypatch):
    fake = _FakeSB()
    monkeypatch.setattr(database, "supabase", fake)
    database.insert_pricing_tiers(7, [_t(**_ev()), _t("B", 5.0, evidence_url=OWN + "/reg",
                                                         evidence_identity="strong")])
    assert [(r["evidence_url"], r["evidence_identity"], r["written_by"]) for r in fake.rows] == [
        (OWN, "own_page", "scraper"), (OWN + "/reg", "strong", "scraper")]


@pytest.mark.parametrize("bad", [
    {},                                                                    # no keys at all
    {"evidence_url": OWN},                                                 # no identity
    {"evidence_identity": "own_page"},                                     # no url
    {"evidence_url": OWN, "evidence_identity": "legacy"},                  # not writable
    {"evidence_url": OWN, "evidence_identity": "weak"},
    {"evidence_url": "", "evidence_identity": "strong"},
])
def test_insert_drops_the_whole_batch_without_provenance(monkeypatch, caplog, bad):
    fake = _FakeSB()
    monkeypatch.setattr(database, "supabase", fake)
    with caplog.at_level(logging.WARNING):
        database.insert_pricing_tiers(7, [_t(**_ev()), _t("Other", 9.0, **bad)])
    assert fake.rows is None and fake.calls == 0           # the good tier is dropped with it
    assert "provenance_rejected" in caplog.text


def test_tiers_have_provenance_helper():
    assert database.tiers_have_provenance([_t(**_ev())])
    assert not database.tiers_have_provenance([_t(**_ev()), _t()])
    assert database.tiers_have_provenance([])


# ======================================================================
# 2. scraper-side producers: extractor page + discovery
# ======================================================================
def test_extractor_tiers_are_stamped_with_the_fetched_page():
    from llm_agent import AgentLoop
    merged = {"pricing_tiers": [_t(), _t("Kept", 9.0, evidence_url="https://x/y", evidence_identity="strong")]}
    AgentLoop._stamp_own_page_tiers(merged, OWN)
    assert (merged["pricing_tiers"][0]["evidence_url"], merged["pricing_tiers"][0]["evidence_identity"]) == (OWN, "own_page")
    assert merged["pricing_tiers"][1]["evidence_url"] == "https://x/y"      # an extractor's own evidence is kept


BASE = "https://conf.example.org/event/annual-2027/"
MAIN = """<html><body><nav>
<a href="/event/annual-2027/registration">Registration</a>
<a href="/event/annual-2027/travel">Travel</a>
<a href="/event/annual-2027/call-for-papers">Call for papers</a>
</nav><h1>Annual Meeting 2027</h1><p>Welcome to the Annual Meeting.</p></body></html>"""
REG = ("<html><body><h1>Annual Meeting 2027 registration</h1><h2>Registration fees</h2>"
       "<p>Member: £120</p><p>Non-member: £180</p><p>Student: £60</p></body></html>")
TRAVEL = ("<html><body><h1>Annual Meeting 2027 travel</h1><p>Venue: Grand Hall, Queen Street, Leeds</p>"
          "</body></html>")
CFP = ("<html><body><h1>Annual Meeting 2027 call for papers</h1>"
       "<p>Abstract submission deadline: 30 June 2099.</p><p>Submit your abstract online.</p></body></html>")


class Net:
    def __init__(self, pages):
        self.pages = pages

    def __call__(self, url, timeout):
        return self.pages.get(url)


def _row(**kw):
    r = {"conference_name": "Annual Meeting 2027", "start_date": "2099-09-01", "event_format": "in_person",
         "booking_url": BASE, "source_url": BASE, "pricing_tiers": [], "venue_name": None, "city": None}
    r.update(kw)
    return r


@pytest.fixture
def _no_net(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_html", lambda u, t: pytest.fail(f"unexpected fetch {u}"))
    monkeypatch.setattr(discovery, "_fetch_bytes", lambda *a, **k: pytest.fail("unexpected pdf fetch"))
    monkeypatch.setattr(discovery, "_vision_pricing", lambda *a, **k: pytest.fail("unexpected vision"))
    monkeypatch.setattr(discovery, "_vision_allowed", lambda: True)


def test_discovery_per_field_evidence_from_subpages(monkeypatch, _no_net):
    # discovery fetches at most two sub-pages per row: fees + venue here, abstract below
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": REG, BASE + "travel": TRAVEL,
                                                       BASE + "call-for-papers": CFP}))
    res = discover(_row(abstract_open=True), MAIN, "", BASE)
    assert res.evidence_for("pricing_tiers") == {"url": BASE + "registration", "identity": "strong"}
    assert res.evidence_for("venue") == {"url": BASE + "travel", "identity": "strong"}
    assert res.evidence_for("abstract") is None
    assert res.evidence_for("nothing") is None
    res2 = discover(_row(pricing_tiers=[{"a": 1}], event_format="online"), MAIN, "", BASE)
    assert res2.evidence_for("abstract") == {"url": BASE + "call-for-papers", "identity": "strong"}


def test_discovery_own_page_evidence(monkeypatch, _no_net):
    own = ("<html><body><h1>Annual Meeting 2027</h1><h2>Registration fees</h2>"
           "<p>Member: £120</p><p>Non-member: £180</p></body></html>")
    res = discover(_row(event_format="online", abstract_open=True), own, "", BASE)
    assert res.tiers
    assert res.evidence_for("pricing_tiers") == {"url": BASE, "identity": "own_page"}


def test_apply_to_row_carries_evidence_into_tiers_and_columns(monkeypatch, _no_net):
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": REG, BASE + "travel": TRAVEL,
                                                       BASE + "call-for-papers": CFP}))
    r = _row(abstract_open=True)
    written = apply_to_row(r, discover(r, MAIN, "", BASE))
    assert {"pricing_tiers", "venue_name"} <= set(written)
    assert all(t["evidence_url"] == BASE + "registration" and t["evidence_identity"] == "strong"
               for t in r["pricing_tiers"])
    assert database.tiers_have_provenance(r["pricing_tiers"])
    assert (r["venue_evidence_url"], r["venue_evidence_identity"]) == (BASE + "travel", "strong")
    r2 = _row(pricing_tiers=[{"a": 1}], event_format="online")
    assert "abstract" in apply_to_row(r2, discover(r2, MAIN, "", BASE))
    assert (r2["abstract_evidence_url"], r2["abstract_evidence_identity"]) == (BASE + "call-for-papers", "strong")


def test_agent_hook_rides_the_evidence_to_the_row(monkeypatch, _no_net):
    from llm_agent import AgentLoop
    monkeypatch.setattr(discovery, "_fetch_html", Net({BASE + "registration": REG}))
    page = types.SimpleNamespace(content=lambda: MAIN, url=BASE)
    browser = types.SimpleNamespace(page=page, get_page_text=lambda: "Annual Meeting")
    ag = types.SimpleNamespace(extractor=types.SimpleNamespace(), browser=browser)
    merged = _row(venue_name="V", city="C", abstract_open=True)
    AgentLoop._discover_missing(ag, merged, BASE)
    assert merged["pricing_tiers"] and database.tiers_have_provenance(merged["pricing_tiers"])


# ======================================================================
# 3. remediator explorer evidence, route by route
# ======================================================================
SB = "https://www.soc.org/events/2027/annual-meeting"
ROW = {"id": 1, "conference_name": "Society Annual Meeting 2027", "start_date": "2027-05-10",
       "source_url": SB}


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    explorer.reset_fetch_state()
    monkeypatch.setattr(explorer, "render_page", lambda url: (None, None, []))
    yield
    explorer.reset_fetch_state()


def fake_pages(monkeypatch, pages):
    def fetch(url, **kw):
        h = pages.get(url)
        if h is None:
            return None, None
        t = _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))).strip()
        return t, h
    monkeypatch.setattr(explorer, "fetch_page_text_and_html", fetch)


def _price(row=ROW, text="Society Annual Meeting 2027", html="", **kw):
    return explorer.explore_for_pricing(row=row, page_text=text, page_html=html or None, base_url=SB,
                                        llm_call=kw.get("llm", lambda p: None))


def test_pricing_main_page_text_is_own_page(monkeypatch):
    res = _price(text="Society Annual Meeting 2027. Registration fees: Member £120, Non-member £180", html="")
    assert res.found
    assert (res.evidence_url, res.evidence_identity) == (SB, "own_page")
    assert res.to_dict()["evidence_url"] == SB


TABLE = ("<table><tr><th>Ticket</th><th>Fee</th></tr><tr><td>Whole conference member</td><td>£795</td></tr>"
         "<tr><td>Whole conference non-member</td><td>£995</td></tr></table>")


def test_pricing_same_site_subpage_is_strong(monkeypatch):
    reg = SB + "/registration"
    main = f'<html><body><h1>Society Annual Meeting 2027</h1><nav><a href="{reg}">Registration</a></nav></body></html>'
    fake_pages(monkeypatch, {SB: main, reg: f"<html><body><h1>Society Annual Meeting 2027 registration</h1>{TABLE}</body></html>"})
    res = _price(html=main, text="x")
    assert res.found and (res.evidence_url, res.evidence_identity) == (reg, "strong")


def test_pricing_organiser_url_page_is_strong(monkeypatch):
    org = "https://congress.example.org/am27"
    main = "<html><body><p>Society Annual Meeting 2027</p></body></html>"
    fake_pages(monkeypatch, {SB: main, org: f"<html><body><h1>Society Annual Meeting 2027</h1>{TABLE}</body></html>"})
    res = _price(row={**ROW, "organiser_url": org}, html=main, text="x")
    assert res.found and res.external_url == org
    assert (res.evidence_url, res.evidence_identity) == (org, "strong")


def test_pricing_generic_external_page_is_discarded(monkeypatch):
    other = "https://congress.example.org/am27"
    main = f'<html><body><p>Society Annual Meeting 2027</p><a href="{other}">Register now</a></body></html>'
    fake_pages(monkeypatch, {SB: main, other: f"<html><body><h1>Delegate registration</h1>{TABLE}</body></html>"})
    res = _price(row={**ROW, "organiser_url": "https://elsewhere.example.org/"}, html=main, text="x")
    assert not res.found and res.evidence_url is None
    assert any(f"provenance_rejected: {other}" in str(n) for n in res.audit_trail.notes)


def test_pricing_external_page_whose_h1_is_the_title_is_strong(monkeypatch):
    other = "https://congress.example.org/am27"
    main = f'<html><body><p>Society Annual Meeting 2027</p><a href="{other}">Register now</a></body></html>'
    fake_pages(monkeypatch, {SB: main, other: f"<html><body><h1>Society Annual Meeting 2027</h1>{TABLE}</body></html>"})
    res = _price(html=main, text="x")
    assert res.found and (res.evidence_url, res.evidence_identity) == (other, "strong")


def test_pricing_organiser_site_subpage_under_its_path_is_strong(monkeypatch):
    org = "https://congress.example.org/am27"
    reg = org + "/registration"
    main = "<html><body><p>Society Annual Meeting 2027</p></body></html>"
    fake_pages(monkeypatch, {SB: main,
                             org: f'<html><body><p>Society Annual Meeting 2027</p><a href="{reg}">Registration</a></body></html>',
                             reg: f"<html><body><h1>Registration</h1><p>Society Annual Meeting 2027</p>{TABLE}</body></html>"})
    res = _price(row={**ROW, "organiser_url": org}, html=main, text="x")
    assert res.found and (res.evidence_url, res.evidence_identity) == (reg, "strong")


def test_pricing_sibling_event_page_on_the_organiser_host_is_rejected(monkeypatch):
    org = "https://congress.example.org/am27"
    sib = "https://congress.example.org/am26-registration"
    main = "<html><body><p>Society Annual Meeting 2027</p></body></html>"
    fake_pages(monkeypatch, {SB: main,
                             org: f'<html><body><p>Society Annual Meeting 2027</p><a href="{sib}">Registration</a></body></html>',
                             sib: f"<html><body><h1>Registration</h1>{TABLE}</body></html>"})
    res = _price(row={**ROW, "organiser_url": org}, html=main, text="x")
    assert not res.found
    assert any(f"provenance_rejected: {sib}" in str(n) for n in res.audit_trail.notes)


def test_pricing_ticketing_link_eligible_only_when_it_is_the_booking_url(monkeypatch):
    eb = "https://www.eventbrite.co.uk/e/society-annual-meeting-2027-tickets-123"
    ld = ('<script type="application/ld+json">{"@type":"Event","offers":[{"@type":"Offer","name":"Delegate",'
          '"price":"95","priceCurrency":"GBP"}]}</script>')
    main = f'<html><body><p>Society Annual Meeting 2027</p><a href="{eb}">Book</a></body></html>'
    fake_pages(monkeypatch, {SB: main, eb: f"<html><body>Society Annual Meeting 2027 {ld}</body></html>"})
    assert not _price(row=ROW, html=main, text="x").found
    ok = _price(row={**ROW, "booking_url": eb}, html=main, text="x")
    assert ok.found and (ok.evidence_url, ok.evidence_identity) == (eb, "strong")


def test_fee_document_inherits_the_linking_page(monkeypatch):
    from remediator import pdf_text
    monkeypatch.setattr(explorer, "_fetch_document_text", lambda u, tr: "Registration fees\nMember £200\nStandard £300\n")
    monkeypatch.setattr(pdf_text, "document_text_gate", lambda text, row=None: (True, "ok"))
    hit = explorer._follow_fee_document('<a href="/a/fees.pdf">Fees</a>', "https://e.org/p", ExploreBudget(), AuditTrail())
    tiers, url, method = hit
    assert tiers and url.endswith("fees.pdf") and hit.page == "https://e.org/p"


def test_locate_evidence_picks_the_page_that_holds_the_prices():
    tiers = [{"price_gbp": 120.0}, {"price_gbp": 180.0}]
    sources = [(SB, "own_page", "Welcome. nothing priced here"),
               (SB + "/registration", "strong", "Member £120 Non-member £180")]
    assert explorer._locate_evidence(tiers, sources) == (SB + "/registration", "strong")
    assert explorer._locate_evidence([{"price_gbp": 999.0}], sources) is None
    assert explorer._locate_evidence([{"price_gbp": 1200.0}], [(SB, "own_page", "Fee £1,200")]) == (SB, "own_page")


def test_llm_full_context_carries_located_evidence_or_is_discarded(monkeypatch):
    reg = SB + "/registration"
    main = f'<html><body><h1>Society Annual Meeting 2027</h1><nav><a href="{reg}">Registration</a></nav></body></html>'
    sub = ("<html><body><h1>Society Annual Meeting 2027 registration</h1>"
           "<p>Delegates pay one hundred and twenty pounds, that is 120 GBP in total.</p></body></html>")
    fake_pages(monkeypatch, {SB: main, reg: sub})
    good = '{"tiers":[{"tier_label":"Delegate","price":120,"currency":"GBP"}],"reasoning":"r"}'
    res = _price(html=main, text="x", llm=lambda p: good)
    assert res.found and res.method == "llm_full_context"
    assert (res.evidence_url, res.evidence_identity) == (reg, "strong")
    bad = '{"tiers":[{"tier_label":"Delegate","price":777,"currency":"GBP"}],"reasoning":"r"}'
    res2 = _price(html=main, text="x", llm=lambda p: bad)
    assert not res2.found
    assert any("provenance_rejected" in str(n) for n in res2.audit_trail.notes)


# ---- abstract explorer
def _abstract(row=ROW, text="Society Annual Meeting 2027", html=None):
    return explorer.explore_for_abstract_status(row=row, page_text=text, page_html=html, base_url=SB,
                                                llm_call=lambda p: None)


def _stub_abstract_fixer(monkeypatch, needle="deadline of 1 August"):
    import remediator.fixers.abstract as fa
    monkeypatch.setattr(fa, "fix_abstract_status",
                        lambda row, text, llm: ({"abstract_open": True, "abstract_deadline": "2027-08-01"}, "stub")
                        if needle in text else ({"abstract_open": False}, "no_abstract_mention")
                        if "abstract" not in text.lower() else (None, None))


def test_abstract_main_page_is_own_page(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    res = _abstract(text="Abstracts: deadline of 1 August")
    assert res.found and (res.evidence_url, res.evidence_identity) == (SB, "own_page")


def test_abstract_same_site_subpage_is_strong(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    ab = SB + "/abstracts"
    main = f'<html><body><p>Society Annual Meeting 2027</p><a href="{ab}">Abstracts</a></body></html>'
    fake_pages(monkeypatch, {SB: main, ab: "<html><body><h1>Society Annual Meeting 2027 abstracts</h1>"
                                           "<p>Abstracts: deadline of 1 August</p></body></html>"})
    res = _abstract(html=main)
    assert res.found and (res.evidence_url, res.evidence_identity) == (ab, "strong")


HOST = "https://www.rcpsych.ac.uk"
CONGRESS = HOST + "/events/congress/international-congress-2026/abstracts"
ROW_1752 = {"id": 1752, "conference_name": "Faculty of Medical Psychotherapy Annual Conference 2027",
            "start_date": "2027-04-14",
            "source_url": HOST + "/events/conferences/detail/2027/04/14/default-calendar/"
                                 "faculty-of-medical-psychotherapy-annual-conference-2027",
            "_shell_titles": ["International Congress 2026", "Faculty of Medical Psychotherapy Annual Conference 2027"]}


def test_abstract_explorer_rejects_a_congress_subpage(monkeypatch):
    """The reused congress fixture (test_explorer_subpage_identity): an abstracts page of ANOTHER event."""
    _stub_abstract_fixer(monkeypatch)
    base = ROW_1752["source_url"]
    main = (f'<html><body><h1>{ROW_1752["conference_name"]}</h1>'
            f'<nav><a href="{CONGRESS}">Abstracts</a></nav></body></html>')
    fake_pages(monkeypatch, {base: main, CONGRESS: "<html><body><h1>International Congress 2026 - Abstracts</h1>"
                                                   "<p>Abstracts: deadline of 1 August</p></body></html>"})
    res = explorer.explore_for_abstract_status(row=ROW_1752, page_text="x", page_html=main, base_url=base,
                                               llm_call=lambda p: None)
    assert not (res.found and res.value and res.value.get("abstract_deadline"))
    assert res.evidence_url != CONGRESS
    assert any(str(n).startswith(f"subpage_rejected: {CONGRESS}") for n in res.audit_trail.notes)


def test_abstract_organiser_url_page_and_its_subpage_are_strong(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    org = "https://congress.example.org/am27/"
    sub = "https://congress.example.org/am27/abstracts/"
    main = "<html><body><p>Society Annual Meeting 2027 stub</p></body></html>"
    fake_pages(monkeypatch, {SB: main,
                             org: "<html><body>Society Annual Meeting 2027 Abstracts: deadline of 1 August</body></html>"})
    res = _abstract(row={**ROW, "organiser_url": org}, text="Society Annual Meeting 2027 stub", html=main)
    assert res.found and (res.evidence_url, res.evidence_identity) == (org, "strong")
    fake_pages(monkeypatch, {SB: main,
                             org: '<html><body>Society Annual Meeting 2027 <a href="/am27/abstracts/">Abstracts</a></body></html>',
                             sub: "<html><body>Society Annual Meeting 2027 abstracts: deadline of 1 August</body></html>"})
    explorer.reset_fetch_state()
    res2 = _abstract(row={**ROW, "organiser_url": org}, text="Society Annual Meeting 2027 stub", html=main)
    assert res2.found and (res2.evidence_url, res2.evidence_identity) == (sub, "strong")


def test_abstract_sibling_page_on_organiser_host_is_rejected(monkeypatch):
    _stub_abstract_fixer(monkeypatch)
    org = "https://congress.example.org/am27/"
    sib = "https://congress.example.org/am26/abstracts/"
    main = "<html><body><p>Society Annual Meeting 2027 stub</p></body></html>"
    fake_pages(monkeypatch, {SB: main,
                             org: f'<html><body>Society Annual Meeting 2027 <a href="{sib}">Abstracts</a></body></html>',
                             sib: "<html><body>Society Annual Meeting 2027 abstracts: deadline of 1 August</body></html>"})
    res = _abstract(row={**ROW, "organiser_url": org}, text="Society Annual Meeting 2027 stub", html=main)
    assert not res.found
    assert any(f"provenance_rejected: {sib}" in str(n) for n in res.audit_trail.notes)


# ---- venue explorer
def _venue(row=ROW, html="<html></html>"):
    kw = dict(row=row, page_text="Society Annual Meeting 2027", page_html=html, base_url=SB, llm_call=lambda p: None)
    return EXPLORERS["venue_name"](**kw)


def test_venue_main_page_is_own_page(monkeypatch):
    main = "<html><body><p>Society Annual Meeting 2027</p><p>Venue: ExCeL London, London</p></body></html>"
    res = _venue(html=main)
    assert res.found and (res.evidence_url, res.evidence_identity) == (SB, "own_page")


def test_venue_same_site_travel_page_is_strong(monkeypatch):
    t = SB + "/travel"
    main = f'<html><body><p>Society Annual Meeting 2027</p><a href="{t}">Getting there</a></body></html>'
    fake_pages(monkeypatch, {SB: main, t: "<html><body><h1>Society Annual Meeting 2027 travel</h1>"
                                          "<p>Venue: Manchester Central, Manchester</p></body></html>"})
    res = _venue(html=main)
    assert res.found and (res.evidence_url, res.evidence_identity) == (t, "strong")


def test_venue_explorer_rejects_a_congress_subpage(monkeypatch):
    base = ROW_1752["source_url"]
    t = HOST + "/events/congress/international-congress-2026/venue"
    main = (f'<html><body><h1>{ROW_1752["conference_name"]}</h1><a href="{t}">Venue</a></body></html>')
    fake_pages(monkeypatch, {base: main, t: "<html><body><h1>International Congress 2026 - Venue</h1>"
                                            "<p>Venue: ICC Birmingham, Birmingham</p></body></html>"})
    tr = AuditTrail()
    assert explorer.explore_for_venue(ROW_1752, main, base, tr) is None
    assert any(str(n).startswith(f"subpage_rejected: {t}") for n in tr.notes)


def test_venue_organiser_url_page_is_strong(monkeypatch):
    org = "https://congress.example.org/am27"
    main = "<html><body><p>Society Annual Meeting 2027</p></body></html>"
    fake_pages(monkeypatch, {SB: main, org: "<html><body><h1>Society Annual Meeting 2027</h1>"
                                            "<p>Venue: Palais des Congres, Paris</p></body></html>"})
    res = _venue(row={**ROW, "organiser_url": org}, html=main)
    assert res.found and (res.evidence_url, res.evidence_identity) == (org, "strong")


# ======================================================================
# 4. runner._patch_row + the runner's refusal
# ======================================================================
class _Q:
    def __init__(self, sb):
        self.sb, self.payload = sb, None

    def update(self, d): self.payload = d; return self
    def eq(self, *a): return self
    def is_(self, *a): return self
    def execute(self):
        self.sb.updates.append(self.payload)
        return SimpleNamespace(data=[{"id": 1}])


class _SB:
    def __init__(self):
        self.updates, self.rpcs = [], []

    def table(self, name): return _Q(self)

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=len(params["p_tiers"])))


def test_patch_row_venue_and_city_write_the_venue_evidence_columns():
    sb = _SB()
    assert runner._patch_row(sb, 1, "venue_name", "Hall", expected=None, evidence=(SB + "/travel", "strong"))
    assert sb.updates[-1] == {"venue_name": "Hall", "venue_evidence_url": SB + "/travel",
                              "venue_evidence_identity": "strong"}
    assert runner._patch_row(sb, 1, "city", "Leeds", expected=None, evidence=(SB, "own_page"))
    assert sb.updates[-1]["venue_evidence_identity"] == "own_page" and sb.updates[-1]["city"] == "Leeds"


def test_patch_row_abstract_writes_the_abstract_evidence_columns():
    sb = _SB()
    val = {"abstract_open": True, "abstract_deadline": "2027-08-01"}
    assert runner._patch_row(sb, 1, "abstract_status", val, expected={}, evidence=(SB + "/abstracts", "strong"))
    assert sb.updates[-1] == {**val, "abstract_evidence_url": SB + "/abstracts",
                              "abstract_evidence_identity": "strong"}
    assert "abstract_evidence_url" not in val                    # the caller's dict is not mutated


@pytest.mark.parametrize("field,value", [("venue_name", "Hall"), ("city", "Leeds"),
                                         ("abstract_status", {"abstract_open": False})])
@pytest.mark.parametrize("ev", [None, (SB, "weak"), (SB, "legacy"), ("", "strong")])
def test_patch_row_refuses_without_valid_evidence(caplog, field, value, ev):
    sb = _SB()
    with caplog.at_level(logging.WARNING):
        assert runner._patch_row(sb, 1, field, value, expected={} if field == "abstract_status" else None,
                                 evidence=ev) is False
    assert sb.updates == [] and "provenance_rejected" in caplog.text


def test_patch_row_pricing_puts_the_keys_inside_each_tier_json():
    sb = _SB()
    assert runner._patch_row(sb, 1, "pricing", [_t(), _t("B", 5.0)], evidence=(SB + "/registration", "strong"))
    _name, params = sb.rpcs[-1]
    assert all(t["evidence_url"] == SB + "/registration" and t["evidence_identity"] == "strong"
               and t["written_by"] == "remediator" for t in params["p_tiers"])


# ---- the runner loop refuses evidence-less explorer results
class _FakeCache:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, u): return "page text"
    def get_html(self, u): return "<html></html>"


class _CapSB(_SB):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def table(self, name):
        sb = self

        class Q(_Q):
            def select(self, *a, **k): return self
            def range(self, *a, **k): return self
            def in_(self, *a, **k): return self
            def execute(self):
                if self.payload is not None:
                    sb.updates.append(self.payload)
                    return SimpleNamespace(data=[{"id": 1}])
                if name == "scraper_sources":
                    return SimpleNamespace(data=[{"id": 5, "society": "S", "source_name": "n"}])
                if name == "conferences":
                    return SimpleNamespace(data=[sb.row])
                return SimpleNamespace(data=[])
        return Q(self)


def _run_loop(monkeypatch, gaps, fixers=None, explorers=None):
    row = {"id": 1, "source_id": 5, "source_url": OWN, "conference_name": "X", "organiser_url": None,
           "booking_url": None, "venue_name": None, "archived": False}
    sb = _CapSB(row)
    monkeypatch.setattr(runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "PageCache", _FakeCache)
    monkeypatch.setattr(runner, "FIXERS", fixers or {})
    monkeypatch.setattr(runner, "EXPLORERS", explorers or {})
    monkeypatch.setattr(runner, "validate", lambda f, v: True)
    monkeypatch.setattr(runner, "detect_gaps_for_rows", lambda c, p: [(r, list(gaps)) for r in c])
    monkeypatch.setattr(runner, "get_promoted_patterns", lambda *a, **k: [])
    monkeypatch.setattr(runner, "record_success", lambda *a, **k: None)
    monkeypatch.setattr(runner, "close_render_browser", lambda: None)
    cap = {}
    monkeypatch.setattr(runner, "write_report", lambda **k: cap.update(k) or "r.json")
    runner.remediate_source(5)
    return sb, cap


def _venue_result(**kw):
    return SimpleNamespace(found=True, value="Hall", method="venue_x", external_url=None, extras={},
                           audit_trail=SimpleNamespace(subpages_fetched=[]), to_dict=lambda: {}, **kw)


def test_runner_refuses_explorer_venue_without_evidence(monkeypatch):
    sb, cap = _run_loop(monkeypatch, ["venue_name"], explorers={"venue_name": lambda **kw: _venue_result()})
    assert [u for u in sb.updates if "venue_name" in u] == []
    assert cap["patches_applied"] == []
    assert cap["patches_couldnt_fix"] and cap["patches_couldnt_fix"][0]["fields"] == ["venue_name"]


def test_runner_writes_explorer_venue_with_its_evidence(monkeypatch):
    res = _venue_result(evidence_url=OWN + "/travel", evidence_identity="strong")
    sb, cap = _run_loop(monkeypatch, ["venue_name"], explorers={"venue_name": lambda **kw: res})
    w = [u for u in sb.updates if "venue_name" in u]
    assert w == [{"venue_name": "Hall", "venue_evidence_url": OWN + "/travel", "venue_evidence_identity": "strong"}]


def test_runner_stamps_a_tier1_fixer_value_as_own_page(monkeypatch):
    sb, _cap = _run_loop(monkeypatch, ["venue_name"], fixers={"venue_name": lambda row, t, llm: ("Hall", "text")})
    w = [u for u in sb.updates if "venue_name" in u]
    assert w == [{"venue_name": "Hall", "venue_evidence_url": OWN, "venue_evidence_identity": "own_page"}]


# ======================================================================
# 5. coverage_report provenance line
# ======================================================================
def test_coverage_provenance_check():
    import coverage_report as cr

    class Res:
        count, data = 3, []

    class Q:
        def __init__(self, err=None): self.err = err
        def table(self, n): return self
        def select(self, *a, **k): return self
        def gte(self, *a): return self
        def is_(self, *a): return self
        def limit(self, *a): return self
        def execute(self):
            if self.err:
                raise self.err
            return Res()

    assert cr.provenance_check(Q()) == ("tiers without provenance written since 2026-10-31: 3", 3)
    line, n = cr.provenance_check(Q(RuntimeError('column pricing_tiers.evidence_identity does not exist')))
    assert (line, n) == ("provenance columns absent", 0)
    line, n = cr.provenance_check(Q(RuntimeError("boom")))
    assert n == 0 and line.startswith("provenance check skipped")
    md = cr.render_markdown({"totals": {"events": 0, "fees_pct": None, "abstracts_pct": None,
                                        "venue_pct": None, "city_pct": None}, "sources": {}},
                            [], "2026-10-31", None, provenance="tiers without provenance written since 2026-10-31: 0")
    assert "tiers without provenance written since 2026-10-31: 0" in md


# ======================================================================
# 6. FV2: listing organiser_url, society homepage, ticketing / microsite recall, extractor evidence
# ======================================================================
def _ee(row, url, html, **kw):
    return explorer.external_evidence(row, url, SB, html, None, **kw)


def _page(h1, body="", title=None):
    t = f"<title>{title}</title>" if title else ""
    return f"<html><head>{t}</head><body><h1>{h1}</h1>{body}{TABLE}</body></html>"


def test_listing_organiser_url_does_not_vouch_for_its_children():
    row = {**ROW, "organiser_url": "https://royalmarsden.example/events"}
    child = "https://royalmarsden.example/events/lung-masterclass/registration"
    assert _ee(row, child, _page("Registration")) is None
    # the same child naming THIS event is fine
    ok = _ee(row, child, _page("Registration", "<p>Society Annual Meeting 2027</p>"))
    assert ok == (child, "strong")


def test_root_organiser_with_registration_page_naming_the_event_is_strong():
    row = {**ROW, "organiser_url": "https://valdisere-vilgrain.com/"}
    reg = "https://valdisere-vilgrain.com/registration"
    assert _ee(row, reg, _page("Society Annual Meeting 2027 registration")) == (reg, "strong")


def test_society_homepage_declared_as_organiser_is_not_evidence(monkeypatch):
    root = "https://society.example/"
    fake_pages(monkeypatch, {root: "<html><body><h1>Welcome to the Society</h1><p>Membership £120</p></body></html>"})
    row = {**ROW, "organiser_url": root}
    assert _ee(row, root, "<html><body><h1>Welcome to the Society</h1><p>Membership £120</p></body></html>") is None


def test_declared_link_with_a_path_still_counts_when_not_rejected():
    row = {**ROW, "organiser_url": "https://soc2.example/meeting"}
    page = "https://soc2.example/meeting"
    assert _ee(row, page, "<html><body><h1>Book your place</h1>£100</body></html>") == (page, "strong")


EB = "https://www.eventbrite.co.uk/e/tickets-99"


def test_ticketing_page_with_title_in_heading_reached_from_own_page_is_strong():
    html = f"<html><head><title>Society Annual Meeting 2027 tickets | Eventbrite</title></head><body>£95</body></html>"
    assert _ee(ROW, EB, html, via_own_page=True) == (EB, "strong")
    other = "<html><head><title>Some other event tickets</title></head><body>£95</body></html>"
    assert _ee(ROW, EB, other, via_own_page=True) is None


ROW_C = {**ROW, "conference_name": "Cardiology Imaging Symposium 2027"}


def test_microsite_root_about_this_event_vouches_for_its_pages(monkeypatch):
    root = "https://abic2027.example/"
    reg = root + "registration"
    fake_pages(monkeypatch, {root: "<html><head><title>Cardiology Imaging Symposium 2027 | Home</title></head>"
                                   "<body><p>Welcome</p></body></html>"})
    row = {**ROW_C, "organiser_url": root}
    assert _ee(row, reg, _page("Registration")) == (reg, "strong")


def test_society_root_that_merely_mentions_the_event_does_not_vouch(monkeypatch):
    root = "https://society.example/"
    reg = root + "membership-registration"
    fake_pages(monkeypatch, {root: "<html><body><h1>Welcome to the Society</h1><p>Our cardiology programme is growing.</p></body></html>"})
    row = {**ROW_C, "organiser_url": root}
    assert _ee(row, reg, _page("Registration")) is None


def test_society_root_naming_the_event_once_in_news_does_not_vouch(monkeypatch):
    root = "https://society.example/"
    fake_pages(monkeypatch, {root: "<html><body><h1>Welcome to the Society</h1><h2>News</h2>"
                                   "<p>Advanced Breast Imaging Course announced. Membership £120.</p></body></html>"})
    row = {**ROW, "conference_name": "Advanced Breast Imaging Course", "organiser_url": root}
    assert _ee(row, root + "registration", "<html><body><h1>Registration</h1><p>£120</p></body></html>") is None


def test_microsite_root_carrying_the_start_date_vouches(monkeypatch):
    root = "https://abic2027.example/"
    fake_pages(monkeypatch, {root: "<html><body><h1>Welcome</h1><p>Join us on 10 May 2027.</p></body></html>"})
    row = {**ROW_C, "organiser_url": root}
    assert _ee(row, root + "registration", _page("Registration")) is not None


def test_root_date_deep_in_the_body_does_not_vouch(monkeypatch):
    root = "https://society.example/"
    filler = "<p>" + "Society news and membership information. " * 30 + "</p>"
    fake_pages(monkeypatch, {root: f"<html><body><h1>Welcome to the Society</h1>{filler}"
                                   "<p>News: Cardiology Imaging Symposium, 10 May 2027.</p></body></html>"})
    row = {**ROW_C, "organiser_url": root}
    assert _ee(row, root + "registration", _page("Registration")) is None


def test_royal_marsden_listing_child_is_rejected_even_with_a_slug_matching_own_path():
    bopa = "https://bopa.org.uk/events/advanced-breast-imaging"
    row = {"id": 2, "conference_name": "Advanced Breast Imaging Course", "start_date": "2027-05-10",
           "source_url": bopa, "booking_url": bopa, "organiser_url": "https://royalmarsden.example/events"}
    child = "https://royalmarsden.example/events/lung-masterclass/registration"
    html = "<html><body><h1>Registration</h1><p>Lung Cancer Masterclass fees £450</p></body></html>"
    assert explorer.external_evidence(row, child, bopa, html, None) is None


def test_extractor_venue_and_abstract_are_stamped_own_page_and_discovery_overrides_only_its_fields():
    from llm_agent import AgentLoop
    merged = {"venue_name": "Hall", "city": "Leeds", "abstract_open": False, "abstract_deadline": None,
              "abstract_deadline_note": None, "venue_evidence_url": "https://stale/", "venue_evidence_identity": "strong"}
    AgentLoop._stamp_own_page_fields(merged, OWN)
    assert (merged["venue_evidence_url"], merged["venue_evidence_identity"]) == (OWN, "own_page")   # stale replaced
    assert "abstract_evidence_url" not in merged                      # nothing to stamp
    merged["abstract_deadline"] = "2027-08-01"
    AgentLoop._stamp_own_page_fields(merged, OWN)
    assert merged["abstract_evidence_identity"] == "own_page"
    # discovery fills only the empty fields: venue keeps the extractor's evidence
    res = discovery.DiscoveryResult(venue_name="Other", city="Other")
    res.field_evidence["venue"] = {"url": "https://x/travel", "identity": "strong"}
    apply_to_row(merged, res)
    assert merged["venue_evidence_url"] == OWN and merged["venue_name"] == "Hall"
