"""B2: detector re-examines frozen rows; runner shared-page guard, learned
pattern replay, fixer order, atomic pattern store. Offline, fake rows only."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from remediator import runner, learned_patterns
from remediator.detector import (detect_gaps, detect_gaps_for_rows,
                                 order_gap_rows, abstract_applicable)
from test_runner_writes import _SB, _conf, _FakeCache

PATTERNS = Path(__file__).resolve().parent.parent / "reports" / "remediation" / "learned_patterns.json"


def _row(**kw):
    base = {"id": 1, "event_type": "course", "event_format": "in_person",
            "venue_name": "V", "city": "London", "description": "x" * 80,
            "cpd_accredited": False, "specialty": "Surgery",
            "abstract_deadline_note": "n/a"}
    base.update(kw)
    return base


def T(label, price):
    return {"tier_label": label, "price_gbp": price}


# ---------------------------------------------------------------- pricing
def test_no_tiers_unchanged():
    assert "pricing" in detect_gaps(_row(), False)

def test_real_tiers_no_gap():
    tiers = [T("Member", 100), T("Non-member", 150)]
    assert "pricing" not in detect_gaps(_row(), True, tiers=tiers)

def test_all_zero_tiers_gap():
    assert "pricing" in detect_gaps(_row(), True, tiers=[T("Standard", 0)])
    assert "pricing" in detect_gaps(_row(), True, tiers=[T("A", 0), T("B", 0.0)])

@pytest.mark.parametrize("label", ["Standard", "Registration", "Registration fee", "Fee", "Fees",
                                   "Price", "Course fee", "Delegate", "  standard "])
def test_single_generic_tier_is_partial(label):
    rows = [(_row(id=7))]
    out = detect_gaps_for_rows(rows, {7: [T(label, 250)]})
    assert out and "pricing" in out[0][1]
    assert out[0][0]["_pricing_gap_kind"] == "partial"

@pytest.mark.parametrize("label", ["standard fee", "Ticket", "General", "Rate", "Event"])
def test_single_label_outside_sql_set_is_no_gap(label):
    """Not in the SQL function's label set: the RPC would return 0, so it is not a gap."""
    out = detect_gaps_for_rows([_row(id=7)], {7: [T(label, 250)]})
    assert not out or "pricing" not in out[0][1]


def test_generic_labels_match_sql_function():
    import re
    from pathlib import Path
    from remediator.detector import REPLACE_GENERIC_LABELS
    sql = (Path(__file__).resolve().parent.parent / "supabase/migrations/20261027000001_remediator_replace_tiers.sql").read_text()
    m = re.search(r"IN \(([^)]*)\)\)\)", sql)
    assert m, "label IN (...) list not found in SQL"
    assert set(re.findall(r"'([^']+)'", m.group(1))) == set(REPLACE_GENERIC_LABELS)


def test_null_price_is_not_zero_like_sql():
    from remediator.detector import pricing_gap_kind
    assert pricing_gap_kind(True, [{"tier_label": "Member", "price_gbp": None}]) is None


def test_more_amounts_than_tiers_is_advisory_not_a_gap():
    from remediator.detector import pricing_gap_kind
    assert pricing_gap_kind(True, [T("Consultant", 99)], 3) == "advisory"

def test_single_specific_tier_no_gap():
    assert "pricing" not in detect_gaps(_row(), True, tiers=[T("Member · Early bird", 99)])
    assert "pricing" not in detect_gaps(_row(), True, tiers=[T("Consultant", 99)])

def test_page_amount_count_hint():
    one = [T("Consultant", 99)]
    assert "pricing" not in detect_gaps(_row(), True, tiers=one)
    assert "pricing" not in detect_gaps(_row(), True, tiers=one, page_amount_count=1)
    assert "pricing" not in detect_gaps(_row(), True, tiers=one, page_amount_count=3)  # advisory only
    generic = [T("Standard", 99)]
    assert "pricing" in detect_gaps(_row(), True, tiers=generic, page_amount_count=3)

def test_zero_tier_rows_order_before_partial():
    now = None
    rows = detect_gaps_for_rows(
        [_row(id=1), _row(id=2)], {1: [T("Standard", 250)]})
    # id 2 has no tiers, id 1 partial; same attempt state -> zero-tier first
    out = [r["id"] for r, _ in order_gap_rows(rows)]
    assert out == [2, 1]

# ------------------------------------------------------------- venue / fmt
def test_hybrid_venue_city_gaps():
    g = detect_gaps(_row(event_format="hybrid", venue_name=None, city=None), True,
                    tiers=[T("Member", 1)])
    assert "venue_name" in g and "city" in g

def test_online_with_stored_city_rechecks_format_not_venue():
    g = detect_gaps(_row(event_format="online", venue_name=None, city="Manchester"),
                    True, tiers=[T("Member", 1)])
    assert "event_format" in g and "venue_name" not in g

def test_online_with_place_in_title():
    g = detect_gaps(_row(event_format="online", venue_name=None, city=None,
                         conference_name="Annual Meeting Edinburgh 2027"),
                    True, tiers=[T("Member", 1)])
    assert "event_format" in g and "venue_name" not in g

def test_plain_online_no_gap():
    g = detect_gaps(_row(event_format="online", venue_name=None, city=None,
                         conference_name="Webinar on sepsis"), True, tiers=[T("M", 1)])
    assert not {"event_format", "venue_name", "city"} & set(g)

# ---------------------------------------------------------------- abstract
def test_abstract_rule_detector():
    base = dict(abstract_deadline_note=None, abstract_deadline=None, abstract_open=None)
    assert "abstract_status" in detect_gaps(_row(event_type="conference", **base), True, tiers=[T("M", 1)])
    assert "abstract_status" in detect_gaps(_row(event_type="workshop", **base), True, tiers=[T("M", 1)])
    assert "abstract_status" not in detect_gaps(_row(event_type="course", **base), True, tiers=[T("M", 1)])
    assert "abstract_status" in detect_gaps(
        _row(event_type="course", conference_name="Course with call for abstracts", **base),
        True, tiers=[T("M", 1)])

def test_abstract_rule_audit_matches_detector():
    from remediator.audit import check_abstract_status
    for et, title, applicable in [("conference", "X", True), ("workshop", "X", True),
                                  ("course", "X", False),
                                  ("course", "Poster abstracts welcome", True)]:
        row = {"event_type": et, "conference_name": title}
        assert abstract_applicable(row) is applicable
        v = check_abstract_status(row, "", "", {})
        assert (v.status != "NOT_APPLICABLE") is applicable, (et, title, v.status)

# ----------------------------------------------------------- learned replay
def _abs_entry():
    d = json.load(open(PATTERNS))
    for e in d["patterns"].values():
        if e.get("promoted") and str(e.get("subpage_path") or "").startswith("http"):
            return e
    pytest.skip("no absolute entry")

def test_resolve_subpage_forms():
    # inline fixtures: the repo's learned_patterns.json may hold no absolute entry
    absolute = "https://easl.eu/events/congress/venue"
    assert learned_patterns.resolve_subpage("https://x.org/event/", absolute) == absolute
    assert learned_patterns.resolve_subpage("https://x.org/event/", "/fees") == "https://x.org/event/fees"
    assert learned_patterns.resolve_subpage("https://x.org/event", "fees") == "https://x.org/event/fees"

class _Cache(_FakeCache):
    fetched = []
    def get(self, u):
        _Cache.fetched.append(u)
        return "page text"

def _drive(monkeypatch, confs, gaps, fixers, explorers=None, promoted=None, cache=None):
    sb = _SB({"scraper_sources": [{"id": 5, "society": "S", "source_name": "n"}],
              "conferences": confs, "pricing_tiers": []})
    _Cache.fetched = []
    monkeypatch.setattr(runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "PageCache", cache or _Cache)
    monkeypatch.setattr(runner, "FIXERS", fixers)
    monkeypatch.setattr(runner, "EXPLORERS", explorers or {})
    monkeypatch.setattr(runner, "validate", lambda f, v: True)
    monkeypatch.setattr(runner, "detect_gaps_for_rows",
                        lambda c, p: [(r, list(gaps)) for r in c])
    monkeypatch.setattr(runner, "get_promoted_patterns", lambda *a, **k: promoted or [])
    monkeypatch.setattr(runner, "record_success", lambda *a, **k: None)
    monkeypatch.setattr(runner, "close_render_browser", lambda: None)
    cap = {}
    monkeypatch.setattr(runner, "write_report", lambda **k: cap.update(k) or "r.json")
    runner.remediate_source(5)
    return sb, cap

def test_replay_uses_absolute_subpage_as_is(monkeypatch):
    e = {"subpage_path": "https://easl.eu/events/congress/venue", "method": "venue_text",
         "promoted": True}
    calls = []
    def fixer(row, text, llm):
        calls.append(text)
        return ("Venue", "text") if len(calls) == 2 else (None, None)
    _drive(monkeypatch, [_conf(source_url="https://easl.eu/events/")], ["venue_name"],
           {"venue_name": fixer}, promoted=[e])
    assert e["subpage_path"] in _Cache.fetched
    assert not any(u.startswith("https://easl.eu/events/https") for u in _Cache.fetched)

# ----------------------------------------------------------- shared page
PAGE = ("Intro. Basic Life Support Course - Fee: £120.\n"
        "Advanced Sepsis Masterclass - Fee: £450 plus VAT.\nFooter")

class _SharedCache(_Cache):
    def get(self, u):
        _Cache.fetched.append(u)
        return PAGE

def test_shared_page_guard(monkeypatch):
    seen = {}
    def pricing_fixer(row, text, llm):
        seen[row["id"]] = text
        return None, None
    explored = []
    confs = [
        _conf(id=1, conference_name="Basic Life Support Course", source_url="https://e.org/c#bls"),
        _conf(id=2, conference_name="Advanced Sepsis Masterclass", source_url="https://e.org/c#sep"),
        _conf(id=3, conference_name="Unrelated Gala Dinner", source_url="https://e.org/c#gala"),
        _conf(id=4, conference_name="Solo", source_url="https://e.org/solo"),
    ]
    monkeypatch.setattr(runner, "PageCache", _SharedCache, raising=False)
    sb = _SB({"scraper_sources": [{"id": 5, "society": "S", "source_name": "n"}],
              "conferences": confs, "pricing_tiers": []})
    monkeypatch.setattr(runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "PageCache", _SharedCache)
    monkeypatch.setattr(runner, "FIXERS", {"pricing": pricing_fixer})
    monkeypatch.setattr(runner, "EXPLORERS",
                        {"pricing": lambda **kw: explored.append(kw["row"]["id"]) or SimpleNamespace(
                            found=False, value=None, to_dict=lambda: {}, external_url=None,
                            extras={}, method="x", audit_trail=SimpleNamespace(subpages_fetched=[]))})
    monkeypatch.setattr(runner, "validate", lambda f, v: True)
    monkeypatch.setattr(runner, "detect_gaps_for_rows",
                        lambda c, p: [(r, ["pricing"]) for r in c])
    monkeypatch.setattr(runner, "get_promoted_patterns", lambda *a, **k: [])
    monkeypatch.setattr(runner, "close_render_browser", lambda: None)
    cap = {}
    monkeypatch.setattr(runner, "write_report", lambda **k: cap.update(k) or "r.json")
    runner.remediate_source(5)
    # sibling text never leaks: row 1's window must not carry row 2's fee
    assert "£120" in seen[1] and "£450" not in seen[1]
    assert "£450" in seen[2] and "£120" not in seen[2]
    assert 3 not in seen            # no identity -> fixer not called
    assert seen[4] == PAGE          # unshared row untouched
    assert explored == [4]          # explorer skipped on shared rows
    assert any(c["conference_id"] == 3 for c in cap["patches_couldnt_fix"])

def test_shared_row_explorer_never_gets_organiser_url(monkeypatch):
    """Even when an explorer is reached for a shared-page row, the organiser_url hop is off."""
    got = []
    confs = [
        _conf(id=1, conference_name="Basic Life Support Course", source_url="https://e.org/c#bls",
              organiser_url="https://other.org/x"),
        _conf(id=2, conference_name="Advanced Sepsis Masterclass", source_url="https://e.org/c#sep",
              organiser_url="https://other.org/y"),
        _conf(id=4, conference_name="Solo", source_url="https://e.org/solo", organiser_url="https://o.org/s"),
    ]
    monkeypatch.setattr(runner, "SHARED_GUARDED_FIELDS", ())   # force the explorer to be reached
    monkeypatch.setattr(runner, "PageCache", _SharedCache)
    expl = lambda **kw: got.append((kw["row"]["id"], kw["row"].get("organiser_url"))) or SimpleNamespace(
        found=False, value=None, to_dict=lambda: {}, external_url="https://other.org/z",
        extras={}, method="x", audit_trail=SimpleNamespace(subpages_fetched=[]))
    sb, cap = _drive(monkeypatch, confs, ["pricing"], {"pricing": lambda r, t, l: (None, None)},
                     explorers={"pricing": expl})
    d = dict(got)
    assert d[1] is None and d[2] is None          # shared rows: hop disabled
    assert d[4] == "https://o.org/s"              # unshared row keeps it


BETA_URL = "https://e.org/events/beta-summit/fees"
BETA_HTML = "<html><h1>Beta Summit 2027</h1><p>Fees. See also Alpha Congress 2027.</p></html>"
BETA_TEXT = "Beta Summit 2027\nFees: Delegate 999 EUR. See also Alpha Congress 2027."


class _ReplayCache(_FakeCache):
    def get(self, u):
        return BETA_TEXT if u == BETA_URL else "main page"
    def get_html(self, u):
        return BETA_HTML if u == BETA_URL else "<html></html>"


def _replay(monkeypatch):
    seen, failures = [], []
    confs = [_conf(id=1, conference_name="Alpha Congress 2027", source_url="https://e.org/events/alpha"),
             _conf(id=2, conference_name="Beta Summit 2027", source_url="https://e.org/events/beta-summit")]
    entry = {"domain": "e.org", "field": "pricing", "method": "subpage", "subpage_path": BETA_URL,
             "hits": 5, "promoted": True}
    def fixer(row, text, llm):
        seen.append((row["id"], text))
        return None, None
    monkeypatch.setattr(runner, "record_failure", lambda e: failures.append(e["subpage_path"]))
    _drive(monkeypatch, confs, ["pricing"], {"pricing": fixer}, promoted=[entry], cache=_ReplayCache)
    return seen, failures


def test_replayed_page_naming_another_event_is_not_used(monkeypatch):
    """Row Alpha mentions-in-passing on Beta's page: token check passes, heading names Beta.
    FV6: Alpha is not under the page's path (never fetched for it); Beta's own page names
    the sibling 'Alpha Congress 2027' in its body -> WEAK in page_identity -> skipped too."""
    seen, failures = _replay(monkeypatch)
    assert (1, BETA_TEXT) not in seen          # never fed Beta's fees to Alpha
    assert (2, BETA_TEXT) not in seen          # fail closed: sibling named in the body
    assert failures == [BETA_URL, BETA_URL]


def test_record_failure_drops_pattern_after_three(monkeypatch, tmp_path):
    monkeypatch.setattr(learned_patterns, "_PATTERNS_PATH", tmp_path / "lp.json")
    for _ in range(3):
        learned_patterns.record_success(source_url="https://e.org/a", field="pricing",
                                        method="subpage", subpage_path=BETA_URL)
    e = learned_patterns.get_promoted_patterns("https://e.org/a", "pricing")[0]
    assert learned_patterns.record_failure(e) is False
    assert learned_patterns.record_failure(e) is False
    assert learned_patterns.get_promoted_patterns("https://e.org/a", "pricing")
    assert learned_patterns.record_failure(e) is True
    assert learned_patterns.get_promoted_patterns("https://e.org/a", "pricing") == []


# ----------------------------------------------------------- fixer order
def test_fixer_order(monkeypatch):
    order = []
    mk = lambda n: (lambda row, t, llm, **kw: order.append(n) or (None, None))
    fx = {n: mk(n) for n in ("description", "cpd_points", "city", "venue_name",
                             "abstract_status", "pricing", "specialty")}
    _drive(monkeypatch, [_conf()],
           ["description", "venue_name", "city", "cpd_points", "specialty", "pricing", "abstract_status"], fx)
    assert order[:4] == ["pricing", "abstract_status", "venue_name", "city"]
    assert set(order[4:]) == {"description", "cpd_points", "specialty"}

# ----------------------------------------------------------- atomic store
def test_patterns_written_atomically(monkeypatch, tmp_path):
    p = tmp_path / "learned_patterns.json"
    monkeypatch.setattr(learned_patterns, "_PATTERNS_PATH", p)
    learned_patterns.record_success(source_url="https://a.org/x", field="pricing", method="m")
    assert json.load(open(p))["patterns"]
    assert [f.name for f in tmp_path.iterdir()] == ["learned_patterns.json"]
    assert learned_patterns.patterns_path() == p


def test_identity_window_prefix_title():
    text = "Sepsis Course Advanced - £500. Sepsis Course - £100. End"
    row = {"conference_name": "Sepsis Course"}
    w = runner.identity_window(row, text, ["Sepsis Course Advanced"])
    assert "£100" in w and "£500" not in w


# ----------------------------------------------------------- FV6 replay guard (fail closed)
class _PeekCache(_FakeCache):
    """PageCache stand-in with the real cache's `_cache` / `_html_cache` dicts."""
    pages: dict = {}
    fetched: list = []

    def __init__(self):
        self._cache, self._html_cache = {}, {}

    def get(self, u):
        _PeekCache.fetched.append(u)
        t, h = _PeekCache.pages.get(u, ("main page", "<html></html>"))
        self._cache[u], self._html_cache[u] = t, h
        return t

    def get_html(self, u):
        if u not in self._html_cache:
            self.get(u)
        return self._html_cache[u]


def _fv6_replay(monkeypatch, confs, sub_url, sub_text, sub_html, pages=None):
    seen, failures = [], []
    _PeekCache.pages = dict(pages or {}, **{sub_url: (sub_text, sub_html)})
    _PeekCache.fetched = []
    entry = {"domain": "x", "field": "pricing", "method": "subpage", "subpage_path": sub_url,
             "hits": 5, "promoted": True}

    def fixer(row, text, llm):
        seen.append((row["id"], text))
        return None, None
    monkeypatch.setattr(runner, "record_failure", lambda e: failures.append(e["subpage_path"]))
    _drive(monkeypatch, confs, ["pricing"], {"pricing": fixer}, promoted=[entry], cache=_PeekCache)
    return seen, failures, list(_PeekCache.fetched)


def test_fv6_replay_easl_congress_never_gets_sld_summit_page(monkeypatch):
    """Reviewer: row 'EASL Congress 2027' vs h1 'SLD Summit 2027', sibling 'EASL SLD Summit 2027'.
    The summit row is processed FIRST, so the page is already cached for the congress row."""
    sub = "https://easl.eu/events/sld-summit-2027/registration"
    confs = [_conf(id=2, conference_name="EASL SLD Summit 2027", start_date="2027-03-01",
                   source_url="https://easl.eu/events/sld-summit-2027"),
             _conf(id=1, conference_name="EASL Congress 2027", start_date="2027-06-01",
                   source_url="https://easl.eu/events/easl-congress-2027")]
    text = "SLD Summit 2027\nRegistration fees\nMember 300 EUR\nOrganised by EASL, 2027"
    seen, failures, _ = _fv6_replay(monkeypatch, confs, sub, text, "<html><h1>SLD Summit 2027</h1></html>")
    assert (1, text) not in seen
    assert (2, text) in seen                  # the summit's own page still replays for the summit
    assert failures == [sub]


def test_fv6_replay_generic_booking_rates_page_is_skipped_without_fetch(monkeypatch):
    sub = "https://brit-thoracic.org.uk/booking-rates"
    confs = [_conf(id=1, conference_name="BTS Summer Meeting 2027", start_date="2027-06-20",
                   source_url="https://brit-thoracic.org.uk/events/summer-meeting-2027")]
    text = "Booking rates\nBTS members £300\nBritish Thoracic Society 2027"
    seen, failures, fetched = _fv6_replay(monkeypatch, confs, sub, text, "<html><h1>Booking rates</h1></html>")
    assert (1, text) not in seen and failures == [sub]
    assert sub not in fetched                 # never fetched: not under the row's own path


def test_fv6_replay_cached_generic_booking_rates_page_is_weak(monkeypatch):
    """Even when the page is already cached (no fetch needed), WEAK identity is skipped."""
    sub = "https://brit-thoracic.org.uk/booking-rates"
    confs = [_conf(id=1, conference_name="BTS Summer Meeting 2027", start_date="2027-06-20",
                   source_url=sub)]                       # row's own page IS the rates page: cached
    confs.append(_conf(id=2, conference_name="BTS Winter Meeting 2027", start_date="2027-12-01",
                       source_url="https://brit-thoracic.org.uk/events/winter-meeting-2027"))
    text = "Booking rates\nBTS members £300\nBritish Thoracic Society 2027"
    seen, failures, _ = _fv6_replay(monkeypatch, confs, sub, text, "<html><h1>Booking rates</h1></html>")
    assert (2, text) not in seen and sub in failures


def test_fv6_replay_own_path_page_naming_another_year_is_skipped(monkeypatch):
    sub = "https://brit-thoracic.org.uk/events/winter-meeting/booking"
    confs = [_conf(id=1, conference_name="BTS Winter Meeting 2027", start_date="2027-12-01",
                   source_url="https://brit-thoracic.org.uk/events/winter-meeting")]
    text = "Winter Meeting 2026 booking rates\nMember £280"
    seen, failures, _ = _fv6_replay(monkeypatch, confs, sub, text,
                                    "<html><h1>Winter Meeting 2026 booking rates</h1></html>")
    assert (1, text) not in seen and failures == [sub]


def test_fv6_replay_per_event_url_fetched_only_for_its_own_row(monkeypatch):
    sub = "https://e.org/events/one/fees"
    confs = [_conf(id=n, conference_name=f"Event Number {n} 2027", start_date="2027-01-01",
                   source_url=f"https://e.org/events/{w}") for n, w in ((1, "one"), (2, "two"), (3, "three"))]
    seen, failures, fetched = _fv6_replay(monkeypatch, confs, sub, "Fees\nMember £10 Event Number 2027",
                                          "<html><h1>Fees</h1></html>")
    assert fetched.count(sub) == 1            # fetched for row 1 (own path) only
    assert sorted(failures) == [sub, sub]     # rows 2 and 3 skipped, demotion counted
