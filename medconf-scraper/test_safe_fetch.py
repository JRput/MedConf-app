"""Mock-only tests for safe_fetch multi-address pinning and verdicts."""
import ssl

import httpx

import safe_fetch

V4 = (2, 1, 6, "", ("93.184.216.34", 443))
V4B = (2, 1, 6, "", ("93.184.216.35", 443))
V6 = (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0))
PRIV = (2, 1, 6, "", ("10.0.0.5", 443))


def _dns(monkeypatch, answers):
    """answers: list of getaddrinfo results, or a dict host->results."""
    def fake(host, *a, **k):
        return answers[host] if isinstance(answers, dict) else answers
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fake)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_second_address_tried_after_connect_error(monkeypatch):
    _dns(monkeypatch, [V6, V4])  # getaddrinfo order: IPv6 first
    hosts = []

    def handler(req):
        hosts.append(req.url.host)
        if ":" in req.url.host:
            raise httpx.ConnectError("Network is unreachable", request=req)
        return httpx.Response(200, text="hello")

    v, final, body, _, st = safe_fetch.fetch_validated("https://example.org/", client=_client(handler))
    assert v == "ok" and st == 200 and body == b"hello"
    assert hosts == ["93.184.216.34"]  # IPv4 preferred, never needed the v6 one


def test_falls_back_v6_when_v4_fails(monkeypatch):
    _dns(monkeypatch, [V4, V6])
    hosts = []

    def handler(req):
        hosts.append(req.url.host)
        if "." in req.url.host:
            raise httpx.ConnectTimeout("t", request=req)
        return httpx.Response(200, text="ok")

    v, *_ = safe_fetch.fetch_validated("https://example.org/", client=_client(handler))
    assert v == "ok" and len(hosts) == 2


def test_any_blocked_address_refuses_host(monkeypatch):
    _dns(monkeypatch, [V4, PRIV])
    calls = []
    c = _client(lambda r: calls.append(r) or httpx.Response(200, text="x"))
    v, *_ = safe_fetch.fetch_validated("https://example.org/", client=c)
    assert v == "rejected" and calls == []


def test_tls_failure_is_tls_error_and_not_retried(monkeypatch):
    _dns(monkeypatch, [V4, V4B])
    calls = []

    def handler(req):
        calls.append(req)
        err = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] hostname mismatch", request=req)
        err.__cause__ = ssl.SSLCertVerificationError("hostname mismatch")
        raise err

    v, *_ = safe_fetch.fetch_validated("https://example.org/", client=_client(handler))
    assert v == "tls_error" and len(calls) == 1


def test_all_addresses_unreachable(monkeypatch):
    _dns(monkeypatch, [V6, V4, V4B])
    calls = []

    def handler(req):
        calls.append(req.url.host)
        raise httpx.ConnectError("Network is unreachable", request=req)

    v, final, *_ = safe_fetch.fetch_validated("https://example.org/", client=_client(handler))
    assert v == "unreachable" and len(calls) == 3 and "ConnectError" in final


def test_redirect_to_private_ip_still_rejected(monkeypatch):
    _dns(monkeypatch, {"example.org": [V4], "evil.example": [PRIV]})

    def handler(req):
        if req.headers["host"] == "example.org":
            return httpx.Response(302, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, text="secret")

    v, hop, *_ = safe_fetch.fetch_validated("https://example.org/", client=_client(handler))
    assert v == "rejected" and "evil.example" in hop


def test_redirect_after_failed_first_address(monkeypatch):
    _dns(monkeypatch, {"example.org": [V6, V4], "other.org": [V4B]})

    def handler(req):
        if ":" in req.url.host:
            raise httpx.ConnectError("unreachable", request=req)
        if req.headers["host"] == "example.org":
            return httpx.Response(301, headers={"location": "https://other.org/"})
        return httpx.Response(200, text="done")

    v, final, body, *_ = safe_fetch.fetch_validated("https://example.org/", client=_client(handler))
    assert v == "ok" and final == "https://other.org/" and body == b"done"


def test_non_2xx_still_blocked(monkeypatch):
    _dns(monkeypatch, [V4])
    v, _, _, _, st = safe_fetch.fetch_validated(
        "https://example.org/", client=_client(lambda r: httpx.Response(403)))
    assert v == "blocked" and st == 403
