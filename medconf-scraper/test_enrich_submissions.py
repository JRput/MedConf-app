"""Tests for enrich_submissions.py: no network, no DB."""
import argparse

import enrich_submissions as es


class FakeCache:
    def __init__(self, text="Fees: lots", html="<html><a href=1><a href=2></html>"):
        self.text, self.html, self.gets = text, html, []

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def get(self, url):
        self.gets.append(url)
        return self.text

    def get_html(self, url): return self.html


class FakeQuery:
    def __init__(self, sb, table): self.sb, self.table, self.op, self.payload = sb, table, "select", None
    def select(self, *a): return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def __getattr__(self, name):  # eq/lt/order/limit
        return lambda *a, **k: self
    def execute(self):
        if self.op == "update":
            self.sb.updates.append((self.table, self.payload))
            return type("R", (), {"data": []})
        return type("R", (), {"data": list(self.sb.data.get(self.table, []))})


class FakeSB:
    def __init__(self, data): self.data, self.updates = data, []
    def table(self, name): return FakeQuery(self, name)


def ok_url(url): return True, ""
no_challenge = lambda html: False
llm = lambda prompt, **kw: None


def submission(**payload):
    base = {"conference_name": "X", "organiser_url": "https://example.org/e",
            "city": "Leeds", "cpd_points": 6}
    base.update(payload)
    return {"id": "u1", "kind": "new_event", "payload": base}


# ---- SSRF guard
def test_ssrf_accepts_public_https(monkeypatch):
    monkeypatch.setattr(es.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert es.check_url_safe("https://example.org/x")[0]


def test_ssrf_rejects(monkeypatch):
    monkeypatch.setattr(es.socket, "getaddrinfo",
                        lambda h, *a, **k: [(2, 1, 6, "", ("10.0.0.5" if h == "internal.test" else "127.0.0.1", 80))])
    for u in ("http://localhost/x", "http://internal.test/x", "http://8.8.8.8/x",
              "http://[::1]/x", "ftp://example.org/x", "", None):
        assert not es.check_url_safe(u)[0], u


# ---- enrichment dict
def test_agrees_true_false_null():
    fixers = {
        "city": lambda r, t, l: ("leeds", "text"),
        "cpd_points": lambda r, t, l: (4, "text"),
        "venue_name": lambda r, t, l: ("Town Hall", "text"),
        "pricing": lambda r, t, l: ([{"tier_label": "A", "price_gbp": 100.0}], "text_regex"),
        "description": lambda r, t, l: (None, None),
    }
    sub = submission(fees={"tiers": [{"label": "Std", "price": 100}]})
    status, enr = es.enrich_one(sub, None, FakeCache(), llm, fixers, no_challenge, ok_url)
    assert status == "fetched"
    assert enr["city"]["agrees"] is True
    assert enr["cpd_points"]["agrees"] is False
    assert enr["venue_name"]["agrees"] is None
    assert enr["pricing"]["agrees"] is True
    assert "description" not in enr


def test_blocked_page():
    status, enr = es.enrich_one(submission(), None, FakeCache(text=""), llm, {}, no_challenge, ok_url)
    assert status == "blocked" and "_error" in enr
    status, _ = es.enrich_one(submission(), None, FakeCache(), llm, {}, lambda h: True, ok_url)
    assert status == "blocked"


def test_rejected_url_skipped():
    status, enr = es.enrich_one(submission(organiser_url="http://localhost/"), None,
                                FakeCache(), llm, {}, no_challenge,
                                lambda u: (False, "localhost"))
    assert (status, enr) == ("skipped", {"_error": "url rejected"})


def test_add_info_uses_conference_url():
    seen = {}
    fixers = {"city": lambda r, t, l: (seen.setdefault("row", r) and "Leeds", "x")}
    conf = {"id": 7, "organiser_url": None, "booking_url": "https://book.example.org/b",
            "source_url": "https://src.example.org", "city": "Old"}
    sub = {"id": "u2", "kind": "add_info", "conference_id": 7,
           "payload": {"fields": {"city": "Leeds"}}}
    cache = FakeCache()
    status, enr = es.enrich_one(sub, conf, cache, llm, fixers, no_challenge, ok_url)
    assert cache.gets[0] == "https://book.example.org/b"
    assert seen["row"]["source_url"] == "https://book.example.org/b"
    assert enr["city"]["agrees"] is True


# ---- run / dry-run
def _run(dry):
    sb = FakeSB({"community_contributions": [submission()]})
    rc = es.run(argparse.Namespace(dry_run=dry, id=None), sb=sb,
                cache_factory=FakeCache, llm_call=llm,
                fixers={"city": lambda r, t, l: ("Leeds", "text")},
                challenge_check=no_challenge, url_check=ok_url)
    return rc, sb


def test_dry_run_writes_nothing():
    rc, sb = _run(True)
    assert rc == 0 and sb.updates == []


def test_real_run_writes():
    rc, sb = _run(False)
    assert rc == 0 and len(sb.updates) == 1
    assert sb.updates[0][1]["enrichment_status"] == "fetched"
