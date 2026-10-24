"""Offline tests: remediator content writes are compare-and-swap.

A write lands only if the stored value still equals what the remediator read,
and pricing tiers are inserted through an atomic DB function that never
deletes. Uses a small stateful fake Supabase (no network).
"""
import copy
import logging
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
            if kind == "eq" and r.get(col) != val:
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
        extras={}, audit_trail=SimpleNamespace(subpages_fetched=[]),
        to_dict=lambda: {})


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


def test_link_patch_precondition(monkeypatch):
    sb = _sb(organiser_url=SRC)

    def explorer(**kw):
        sb.tables["conferences"][0]["organiser_url"] = "https://moderator.example"
        return _pricing_result(external_url="https://org.example/reg")

    applied = _run(monkeypatch, sb, ["pricing"], explorers={"pricing": explorer})
    assert _stored(sb, "organiser_url") == "https://moderator.example"
    assert "organiser_url" not in {p["field"] for p in applied}


def test_no_delete_on_pricing_tiers_anywhere():
    source = Path(runner.__file__).read_text()
    assert 'pricing_tiers").delete()' not in source
