"""Tests for enrich_submissions.py: no network, no DB."""
import argparse

import enrich_submissions as es


class FakeCache:
    """Mimics PageCache's cache attributes; any real fetch is a test failure."""
    def __init__(self):
        self._cache, self._html_cache, self.fetches = {}, {}, []

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def get(self, url):
        if url not in self._cache:
            self.fetches.append(url)
            raise AssertionError(f"PageCache fetched {url}")
        return self._cache[url]

    def get_html(self, url):
        return self._html_cache[url]


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
GOOD = "<html><a href=1>x</a><a href=2>y</a><p>Fees and venue details</p></html>"
passthru = lambda u, c: ("ok", u, GOOD)
def res(html, verdict="ok"): return lambda u, c: (verdict, u, html)


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
    status, enr = es.enrich_one(sub, None, FakeCache(), llm, fixers, no_challenge, ok_url, passthru)
    assert status == "fetched"
    assert enr["city"]["agrees"] is True
    assert enr["cpd_points"]["agrees"] is False
    assert enr["venue_name"]["agrees"] is None
    assert enr["pricing"]["agrees"] is True
    assert "description" not in enr


def test_blocked_page():
    status, enr = es.enrich_one(submission(), None, FakeCache(), llm, {}, no_challenge, ok_url, res("<html></html>"))
    assert status == "blocked" and "_error" in enr
    status, _ = es.enrich_one(submission(), None, FakeCache(), llm, {}, lambda h: True, ok_url, passthru)
    assert status == "blocked"


def test_rejected_url_skipped():
    status, enr = es.enrich_one(submission(organiser_url="http://localhost/"), None,
                                FakeCache(), llm, {}, no_challenge,
                                lambda u: (False, "localhost"), passthru)
    assert status == "skipped" and enr["_error"] == "url rejected" and enr["_checked_url"] is None


def test_add_info_uses_conference_url():
    seen = {}
    fixers = {"city": lambda r, t, l: (seen.setdefault("row", r) and "Leeds", "x")}
    conf = {"id": 7, "organiser_url": None, "booking_url": "https://book.example.org/b",
            "source_url": "https://src.example.org", "city": "Old"}
    sub = {"id": "u2", "kind": "add_info", "conference_id": 7,
           "payload": {"fields": {"city": "Leeds"}}}
    cache = FakeCache()
    seen_urls = []
    resolver = lambda u, c: (seen_urls.append(u) or ("ok", u, GOOD))
    status, enr = es.enrich_one(sub, conf, cache, llm, fixers, no_challenge, ok_url, resolver)
    assert seen_urls == ["https://book.example.org/b"]
    assert seen["row"]["source_url"] == "https://book.example.org/b"
    assert enr["city"]["agrees"] is True


# ---- run / dry-run
def _run(dry):
    sb = FakeSB({"community_contributions": [submission()]})
    rc = es.run(argparse.Namespace(dry_run=dry, id=None), sb=sb,
                cache_factory=FakeCache, llm_call=llm,
                fixers={"city": lambda r, t, l: ("Leeds", "text")},
                challenge_check=no_challenge, url_check=ok_url, resolver=passthru)
    return rc, sb


def test_dry_run_writes_nothing():
    rc, sb = _run(True)
    assert rc == 0 and sb.updates == []


def test_real_run_writes():
    rc, sb = _run(False)
    assert rc == 0 and len(sb.updates) == 1
    assert sb.updates[0][1]["enrichment_status"] == "fetched"


# ---- redirect chain
import httpx


def _client(routes):
    def handler(req):
        loc = routes.get(str(req.url))
        if loc:
            return httpx.Response(302, headers={"location": loc})
        return httpx.Response(200, text=GOOD)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _public_only(u):
    return ("169.254" not in u and "localhost" not in u, "")


def test_redirect_to_metadata_rejected():
    c = _client({"https://a.org/": "http://169.254.169.254/"})
    v, hop, _ = es.resolve_redirect_chain("https://a.org/", _public_only, client=c)
    assert v == "rejected" and "169.254" in hop


def test_redirect_to_public_host_accepted_and_final_fetched():
    c = _client({"https://a.org/": "https://b.org/event"})
    resolver = lambda u, uc: es.resolve_redirect_chain(u, uc, client=c)
    cache = FakeCache()
    status, _ = es.enrich_one(submission(organiser_url="https://a.org/"), None, cache,
                              llm, {}, no_challenge, _public_only, resolver)
    assert status == "fetched" and cache.fetches == []
    assert "https://b.org/event" in cache._cache and "https://a.org/" in cache._cache


def test_too_many_hops_rejected():
    routes = {f"https://h{i}.org/": f"https://h{i+1}.org/" for i in range(10)}
    v, _, _ = es.resolve_redirect_chain("https://h0.org/", ok_url, max_hops=5, client=_client(routes))
    assert v == "rejected"


def test_resolver_returns_validated_body():
    c = _client({"https://a.org/": "https://b.org/event"})
    v, final, html = es.resolve_redirect_chain("https://a.org/", ok_url, client=c)
    assert (v, final) == ("ok", "https://b.org/event")
    assert html == GOOD


def test_html_to_text_strips_scripts():
    assert es.html_to_text("<script>var a=1</script><p>Hi &amp; bye</p>") == "Hi & bye"


def test_browser_fallback_disabled():
    created = []

    class C(FakeCache):
        def __init__(self):
            super().__init__(); self._fetch_browser = "orig"; created.append(self)

    sb = FakeSB({"community_contributions": [submission()]})
    es.run(argparse.Namespace(dry_run=True, id=None), sb=sb, cache_factory=C, llm_call=llm,
           fixers={}, challenge_check=no_challenge, url_check=ok_url, resolver=passthru)
    assert created[0]._fetch_browser("https://x.org") is None


def test_fixers_cannot_reach_network(monkeypatch):
    import remediator.explorer as ex
    import extractors.http_fetch as hf
    called = []
    monkeypatch.setattr(ex, "fetch_page_text_and_html", lambda *a, **k: called.append("ex") or ("x", "y"))
    monkeypatch.setattr(hf, "fetch_html", lambda *a, **k: called.append("hf") or "<html/>")

    def fixer(row, text, l):
        import remediator.explorer as e2
        import extractors.http_fetch as h2
        e2.fetch_page_text_and_html("https://x.org/fees")
        h2.fetch_html("https://x.org/")
        return "v", "m"

    status, enr = es.enrich_one(submission(), None, FakeCache(), llm, {"city": fixer},
                                no_challenge, ok_url, passthru)
    assert status == "fetched" and enr["city"]["value"] == "v"
    assert called == []
    # patches restored afterwards: the sentinels are active again
    ex.fetch_page_text_and_html("u")
    assert called == ["ex"]


def test_submitted_and_checked_urls_recorded():
    c = _client({"https://a.org/": "https://b.org/event"})
    resolver = lambda u, uc: es.resolve_redirect_chain(u, uc, client=c)
    status, enr = es.enrich_one(submission(organiser_url="https://a.org/"), None, FakeCache(),
                                llm, {}, no_challenge, _public_only, resolver)
    assert enr["_submitted_url"] == "https://a.org/"
    assert enr["_checked_url"] == "https://b.org/event"
    assert enr["_rejected_urls"] == []


def test_rejected_extra_urls_listed():
    url_check = lambda u: ("10.0.0.1" not in u, "")
    sub = submission(booking_url="http://10.0.0.1/book", evidence_url="https://ok.org/e")
    status, enr = es.enrich_one(sub, None, FakeCache(), llm, {}, no_challenge, url_check, passthru)
    assert status == "fetched" and enr["_rejected_urls"] == ["http://10.0.0.1/book"]
