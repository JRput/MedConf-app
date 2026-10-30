"""Offline tests: remediator content writes are compare-and-swap.

A write lands only if the stored value still equals what the remediator read,
and pricing tiers are inserted through an atomic DB function that never
deletes. Uses a small stateful fake Supabase (no network).
"""
import copy
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from remediator import runner

SRC = "https://e.org/x"


# ------------------------------------------------------------ stateful fake

class _Q:
    def __init__(self, sb, name):
        self.sb, self.name = sb, name
        self.op, self.payload, self.filters = "select", None, []

    def select(self, *a, **k): return self
    def range(self, *a, **k): return self
    def eq(self, col, val): self.filters.append(("eq", col, val)); return self
    def is_(self, col, val): self.filters.append(("is", col, val)); return self
    def in_(self, col, vals): self.filters.append(("in", col, list(vals))); return self
    def delete(self): self.op = "delete"; return self
    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def update(self, d): self.op, self.payload = "update", d; return self

    def _match(self, r):
        for kind, col, val in self.filters:
            if kind == "eq":
                have = r.get(col)
                if isinstance(have, bool):
                    have = str(have).lower()  # PostgREST compares boolean as true/false text
                if isinstance(val, bool):
                    val = str(val).lower()
                if have != val:
                    return False
            if kind == "is" and not (val == "null" and r.get(col) is None):
                return False
            if kind == "in" and r.get(col) not in val:
                return False
        return True

    def execute(self):
        table = self.sb.tables.setdefault(self.name, [])
        if self.op == "select":
            return SimpleNamespace(data=[copy.deepcopy(r) for r in table if self._match(r)])
        self.sb.writes.append((self.name, self.op, self.payload))
        if self.op == "update":
            hit = [r for r in table if self._match(r)]
            for r in hit:
                r.update(self.payload)
            return SimpleNamespace(data=copy.deepcopy(hit))
        if self.op == "delete":
            hit = [r for r in table if self._match(r)]
            table[:] = [r for r in table if r not in hit]
            return SimpleNamespace(data=hit)
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        table.extend(copy.deepcopy(rows))
        return SimpleNamespace(data=rows)


class _RPC:
    def __init__(self, sb, name, params):
        self.sb, self.name, self.params = sb, name, params

    def execute(self):
        self.sb.writes.append(("rpc", self.name, self.params))
        assert self.name == "remediator_insert_tiers_if_empty"
        cid = self.params["p_conference_id"]
        tiers = self.sb.tables.setdefault("pricing_tiers", [])
        if any(t["conference_id"] == cid for t in tiers):
            return SimpleNamespace(data=0)
        n = 0
        for t in self.params["p_tiers"]:
            if not t.get("tier_label") or t.get("price_gbp") is None:
                continue
            tiers.append({"conference_id": cid, **t})
            n += 1
        return SimpleNamespace(data=n)


class _SB:
    def __init__(self, tables):
        self.tables, self.writes = tables, []

    def table(self, name): return _Q(self, name)
    def rpc(self, name, params): return _RPC(self, name, params)


class _FakeCache:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, u): return "page text"
    def get_html(self, u): return "<html></html>"


def _conf(**kw):
    base = {"id": 1, "source_id": 5, "source_url": SRC, "conference_name": "X",
            "organiser_url": None, "booking_url": None, "venue_name": None,
            "archived": False}
    base.update(kw)
    return base


def _run(monkeypatch, sb, gaps, fixers=None, explorers=None):
    monkeypatch.setattr(runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "PageCache", _FakeCache)
    monkeypatch.setattr(runner, "FIXERS", fixers or {})
    monkeypatch.setattr(runner, "EXPLORERS", explorers or {})
    monkeypatch.setattr(runner, "validate", lambda f, v: True)
    monkeypatch.setattr(runner, "detect_gaps_for_rows",
                        lambda c, p: [(r, list(gaps)) for r in c])
    monkeypatch.setattr(runner, "get_promoted_patterns", lambda *a, **k: [])
    monkeypatch.setattr(runner, "record_success", lambda *a, **k: None)
    monkeypatch.setattr(runner, "close_render_browser", lambda: None)
    monkeypatch.setattr(runner, "write_report", lambda **k: "report.json")
    # remediate_source returns counts only; capture the applied list via report kwargs
    captured = {}
    monkeypatch.setattr(runner, "write_report",
                        lambda **k: captured.update(k) or "report.json")
    runner.remediate_source(5)
    return captured.get("patches_applied", [])


def _sb(**extra):
    t = {"scraper_sources": [{"id": 5, "society": "S", "source_name": "n"}],
         "conferences": [_conf(**extra)], "pricing_tiers": []}
    return _SB(t)


def _pricing_result(external_url=None):
    tier = {"tier_label": "Member", "price_gbp": 100, "currency": "GBP"}
    return SimpleNamespace(
        found=True, value=[tier], method="text", external_url=external_url,
        evidence_url=SRC, evidence_identity="own_page",
        extras={}, audit_trail=SimpleNamespace(subpages_fetched=[]),
        to_dict=lambda: {})


def _no_pricing_delete(sb):
    assert not any(w[0] == "pricing_tiers" and w[1] == "delete" for w in sb.writes)


def _stored(sb, field):
    return sb.tables["conferences"][0][field]


# --------------------------------------------------------------------- tests

def test_concurrent_edit_is_not_overwritten(monkeypatch, caplog):
    sb = _sb()

    def fixer(row, page_text, llm_call):
        sb.tables["conferences"][0]["venue_name"] = "Moderator venue"
        return "Scraped venue", "text"

    with caplog.at_level(logging.WARNING):
        applied = _run(monkeypatch, sb, ["venue_name"], fixers={"venue_name": fixer})
    assert _stored(sb, "venue_name") == "Moderator venue"
    assert [p for p in applied if p["field"] == "venue_name"] == []
    assert "remediator: skipped 1.venue_name: row changed since read" in caplog.text
    _no_pricing_delete(sb)


def test_pricing_not_clobbered_when_tiers_appear(monkeypatch):
    sb = _sb()

    def explorer(**kw):
        sb.tables["pricing_tiers"].append(
            {"conference_id": 1, "tier_label": "Moderator", "price_gbp": 5, "currency": "GBP"})
        return _pricing_result()

    applied = _run(monkeypatch, sb, ["pricing"], explorers={"pricing": explorer})
    assert [t["tier_label"] for t in sb.tables["pricing_tiers"]] == ["Moderator"]
    assert not any(w[0] == "pricing_tiers" and w[1] == "delete" for w in sb.writes)
    assert applied == []
    _no_pricing_delete(sb)


def test_happy_path_still_writes(monkeypatch):
    sb = _sb()
    applied = _run(
        monkeypatch, sb, ["venue_name", "pricing"],
        fixers={"venue_name": lambda row, t, llm: ("Scraped venue", "text")},
        explorers={"pricing": lambda **kw: _pricing_result()})
    assert _stored(sb, "venue_name") == "Scraped venue"
    assert [t["tier_label"] for t in sb.tables["pricing_tiers"]] == ["Member"]
    assert {p["field"] for p in applied} == {"venue_name", "pricing"}
    assert any(w[0] == "rpc" for w in sb.writes)
    _no_pricing_delete(sb)


def test_link_patch_precondition(monkeypatch):
    sb = _sb(organiser_url=SRC)

    def explorer(**kw):
        sb.tables["conferences"][0]["organiser_url"] = "https://moderator.example"
        return _pricing_result(external_url="https://org.example/reg")

    applied = _run(monkeypatch, sb, ["pricing"], explorers={"pricing": explorer})
    assert _stored(sb, "organiser_url") == "https://moderator.example"
    assert "organiser_url" not in {p["field"] for p in applied}
    _no_pricing_delete(sb)


def test_no_delete_on_pricing_tiers_anywhere():
    source = Path(runner.__file__).read_text()
    assert re.search(r'pricing_tiers["\']\s*\)\s*\.\s*delete\s*\(', source) is None


def _no_fees_result():
    r = _pricing_result(external_url="https://org.example/reg")
    r.found, r.value = False, None
    return r


def test_no_fees_organiser_link_happy_path(monkeypatch):
    # Read value is the listing URL (non-NULL): the write must carry it as the precondition.
    sb = _sb(organiser_url=SRC)
    applied = _run(monkeypatch, sb, ["pricing"],
                   explorers={"pricing": lambda **kw: _no_fees_result()})
    assert _stored(sb, "organiser_url") == "https://org.example/reg"
    assert [p["field"] for p in applied] == ["organiser_url"]


def test_no_fees_organiser_link_precondition(monkeypatch):
    sb = _sb(organiser_url=SRC)

    def explorer(**kw):
        sb.tables["conferences"][0]["organiser_url"] = "https://moderator.example"
        return _no_fees_result()

    applied = _run(monkeypatch, sb, ["pricing"], explorers={"pricing": explorer})
    assert _stored(sb, "organiser_url") == "https://moderator.example"
    assert applied == []
    _no_pricing_delete(sb)


PLACEHOLDER = "Call for abstracts - see page for submission date"
AB_VALUE = {"abstract_open": True, "abstract_deadline": "2027-01-31",
            "abstract_deadline_note": "Deadline 31 Jan"}


def test_abstract_status_not_overwritten_when_note_changes(monkeypatch, caplog):
    sb = _sb(abstract_open=True, abstract_deadline=None, abstract_deadline_note=PLACEHOLDER)

    def fixer(row, page_text, llm_call):
        sb.tables["conferences"][0]["abstract_deadline_note"] = "Moderator note"
        return AB_VALUE, "text"

    with caplog.at_level(logging.WARNING):
        applied = _run(monkeypatch, sb, ["abstract_status"], fixers={"abstract_status": fixer})
    assert _stored(sb, "abstract_deadline_note") == "Moderator note"
    assert _stored(sb, "abstract_deadline") is None
    assert applied == []
    assert "skipped 1.abstract_status: row changed since read" in caplog.text
    _no_pricing_delete(sb)


def test_abstract_status_happy_path(monkeypatch):
    sb = _sb(abstract_open=True, abstract_deadline=None, abstract_deadline_note=PLACEHOLDER)
    applied = _run(monkeypatch, sb, ["abstract_status"],
                   fixers={"abstract_status": lambda row, t, llm: (AB_VALUE, "text")})
    assert _stored(sb, "abstract_deadline") == "2027-01-31"
    assert _stored(sb, "abstract_deadline_note") == "Deadline 31 Jan"
    assert [p["field"] for p in applied] == ["abstract_status"]
    _no_pricing_delete(sb)


def test_abstract_status_side_finding_not_overwritten(monkeypatch):
    sb = _sb(abstract_open=True, abstract_deadline=None, abstract_deadline_note=PLACEHOLDER)

    def explorer(**kw):
        sb.tables["conferences"][0]["abstract_open"] = False  # concurrent edit
        r = _pricing_result()
        r.extras = {"abstract_status": AB_VALUE,
                    "abstract_status_evidence": {"url": SRC, "identity": "strong"}}
        return r

    applied = _run(monkeypatch, sb, ["pricing", "abstract_status"],
                   explorers={"pricing": explorer})
    assert _stored(sb, "abstract_open") is False
    assert _stored(sb, "abstract_deadline") is None
    assert "abstract_status" not in {p["field"] for p in applied}
    _no_pricing_delete(sb)


def test_abstract_status_side_finding_happy_path(monkeypatch):
    sb = _sb(abstract_open=True, abstract_deadline=None, abstract_deadline_note=PLACEHOLDER)

    def explorer(**kw):
        r = _pricing_result()
        r.extras = {"abstract_status": AB_VALUE,
                    "abstract_status_evidence": {"url": SRC, "identity": "strong"}}
        return r

    applied = _run(monkeypatch, sb, ["pricing", "abstract_status"],
                   explorers={"pricing": explorer})
    assert _stored(sb, "abstract_deadline") == "2027-01-31"
    assert "abstract_status" in {p["field"] for p in applied}


def test_rpc_non_int_result_is_not_success(caplog):
    class _SBStub:
        def rpc(self, name, params):
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"x": 1}]))

    with caplog.at_level(logging.WARNING):
        ok = runner._patch_row(_SBStub(), 1, "pricing",
                               [{"tier_label": "M", "price_gbp": 1}])
    assert ok is False
    assert "unexpected tier rpc result" in caplog.text
    assert "[{'x': 1}]" in caplog.text
