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

@pytest.mark.parametrize("label", ["Standard", "Registration", "Fee", "Price",
                                   "Course fee", "standard fee"])
def test_single_generic_tier_is_partial(label):
    rows = [(_row(id=7))]
    out = detect_gaps_for_rows(rows, {7: [T(label, 250)]})
    assert out and "pricing" in out[0][1]
    assert out[0][0]["_pricing_gap_kind"] == "partial"

def test_single_specific_tier_no_gap():
    assert "pricing" not in detect_gaps(_row(), True, tiers=[T("Member · Early bird", 99)])
    assert "pricing" not in detect_gaps(_row(), True, tiers=[T("Consultant", 99)])

def test_page_amount_count_hint():
    one = [T("Consultant", 99)]
    assert "pricing" not in detect_gaps(_row(), True, tiers=one)
    assert "pricing" not in detect_gaps(_row(), True, tiers=one, page_amount_count=1)
    assert "pricing" in detect_gaps(_row(), True, tiers=one, page_amount_count=3)

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

def _drive(monkeypatch, confs, gaps, fixers, explorers=None, promoted=None):
    sb = _SB({"scraper_sources": [{"id": 5, "society": "S", "source_name": "n"}],
              "conferences": confs, "pricing_tiers": []})
    _Cache.fetched = []
    monkeypatch.setattr(runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "PageCache", _Cache)
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
