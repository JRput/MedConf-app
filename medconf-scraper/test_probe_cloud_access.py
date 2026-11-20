"""Unit tests for probe_cloud_access: production-path verdicts, no network."""
import probe_cloud_access as p

REAL = "<html><body>" + "".join(f'<a href="/p{i}">page {i}</a>' for i in range(30)) + ("x" * 800) + "</body></html>"
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Checking your browser <a href='/a'>a</a></body></html>"


class FakeBrowser:
    page = None


def run(url, fetch, problems):
    def reset():
        problems.update(blocked=0, unreachable=0, url={})
    return p.production_probe(url, FakeBrowser(), fetch=fetch, reset=reset, problems=problems)


def test_real_body_is_cleared():
    probs = {"blocked": 0, "unreachable": 0, "url": {}}
    r = run("https://a.test/", lambda u, browser=None: REAL, probs)
    assert r["ok"] and not r["challenge"] and not r["blocked"] and not r["unreachable"]
    assert r["length"] == len(REAL) and isinstance(r["elapsed_ms"], int)


def test_403_then_challenge_is_challenged():
    probs = {"blocked": 0, "unreachable": 0, "url": {}}

    def fetch(u, browser=None):  # httpx 403, browser fallback shows a challenge: fetch_html returns None and records blocked
        probs["blocked"] += 1
        return None
    r = run("https://b.test/", fetch, probs)
    assert not r["ok"] and r["blocked"] and not r["unreachable"]
    # a challenge page that slips through as a body is also not ok
    r2 = run("https://b.test/", lambda u, browser=None: CHALLENGE, {"blocked": 0, "unreachable": 0, "url": {}})
    assert not r2["ok"] and r2["challenge"] and r2["blocked"]


def test_transport_failure_is_unreachable():
    probs = {"blocked": 0, "unreachable": 0, "url": {}}

    def fetch(u, browser=None):
        probs["unreachable"] += 1
        return None
    r = run("https://c.test/", fetch, probs)
    assert not r["ok"] and r["unreachable"] and not r["blocked"] and r["length"] == 0


def test_fetch_exception_does_not_kill_probe():
    def boom(u, browser=None):
        raise RuntimeError("x")
    r = run("https://d.test/", boom, {"blocked": 0, "unreachable": 0, "url": {}})
    assert not r["ok"]


def _prod(outcomes):
    def prod(url, browser):
        return outcomes[url]
    return prod


OK = {"ok": True, "length": 9000, "challenge": False, "blocked": False, "unreachable": False, "elapsed_ms": 5}
BLK = {"ok": False, "length": 0, "challenge": False, "blocked": True, "unreachable": False, "elapsed_ms": 5}
UNR = {"ok": False, "length": 0, "challenge": False, "blocked": False, "unreachable": True, "elapsed_ms": 5}


def fake_brow(url, browser):
    return {"url": url, "cleared": True, "secs": 0.1}  # browser alone "clears" everything, as on 2026-11-09


def test_domain_verdict_picks_first_clearing_url_and_stops():
    seen = []

    def prod(url, browser):
        seen.append(url)
        return {"u1": BLK, "u2": OK, "u3": OK}[url]
    rec = p.probe_domain({"domain": "x.test", "candidate_urls": ["u1", "u2", "u3"]}, None, prod=prod, brow=fake_brow)
    assert rec["verdict"] == "cleared" and rec["cleared"] and rec["cleared_url"] == "u2"
    assert seen == ["u1", "u2"]
    assert all("production_fetch" in r for r in rec["results"])


def test_browser_only_clear_does_not_clear_domain():
    rec = p.probe_domain({"domain": "x.test", "candidate_urls": ["u1"]}, None, prod=_prod({"u1": BLK}), brow=fake_brow)
    assert rec["verdict"] == "challenged" and not rec["cleared"] and rec["browser_cleared"]


def test_domain_unreachable_and_mixed():
    rec = p.probe_domain({"domain": "x.test", "candidate_urls": ["u1", "u2"]}, None, prod=_prod({"u1": UNR, "u2": UNR}), brow=fake_brow)
    assert rec["verdict"] == "unreachable" and rec["cleared_url"] is None
    rec = p.probe_domain({"domain": "x.test", "candidate_urls": ["u1", "u2"]}, None, prod=_prod({"u1": UNR, "u2": BLK}), brow=fake_brow)
    assert rec["verdict"] == "challenged"
