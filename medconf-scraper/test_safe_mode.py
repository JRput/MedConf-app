"""Offline tests for REMEDIATOR_SAFE_FETCH (safe-fetch mode for community rows).

With the flag on, no plain httpx client, no httpx.get and no Playwright may be
reached from the remediator's fetch paths; loopback and redirect-to-internal
targets are refused; PDFs are capped and parsed in a subprocess; source-1000
rows never get URL fields patched.
"""
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import httpx
import pytest

import safe_fetch
from extractors import abstract_classifier, http_fetch
from remediator import explorer, fetcher, pdf_text, runner
import vision

_RealClient = httpx.Client


# ------------------------------------------------------------------ fixtures

class _Handler(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):  # noqa: N802
        _Handler.hits.append(self.path)
        if self.path.startswith("/redir"):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        body = b'<html><body><a href="/fees.pdf">Fees</a> hello</body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    _Handler.hits = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def safe_on(monkeypatch):
    """Flag on. Records every plain-client / httpx.get / Playwright use in
    `rec["hits"]` (callers swallow exceptions, so raising alone proves nothing)
    and every SafeClient.get / fetch_validated call in `rec["safe"]`."""
    monkeypatch.setenv("REMEDIATOR_SAFE_FETCH", "1")
    rec = {"hits": [], "safe": []}

    def guarded_client(*a, **k):
        # safe_fetch's own pinned client is the one allowed constructor.
        caller = sys._getframe(1).f_globals.get("__name__")
        if caller == "safe_fetch":
            return _RealClient(*a, **k)
        rec["hits"].append(("httpx.Client", caller))
        raise AssertionError("plain client used")

    def no_get(*a, **k):
        rec["hits"].append(("httpx.get", sys._getframe(1).f_globals.get("__name__")))
        raise AssertionError("plain client used")

    def no_pw(*a, **k):
        rec["hits"].append(("playwright", sys._getframe(1).f_globals.get("__name__")))
        raise AssertionError("playwright used")

    monkeypatch.setattr(httpx, "Client", guarded_client)
    monkeypatch.setattr(httpx, "get", no_get)
    import browser
    import playwright.sync_api as pw
    monkeypatch.setattr(pw, "sync_playwright", no_pw)
    monkeypatch.setattr(browser, "sync_playwright", no_pw)

    orig_get = safe_fetch.SafeClient.get
    orig_fv = safe_fetch.fetch_validated

    def rec_get(self, url):
        rec["safe"].append(("SafeClient.get", url))
        return orig_get(self, url)

    def rec_fv(url, *a, **k):
        rec["safe"].append(("fetch_validated", url))
        return orig_fv(url, *a, **k)

    monkeypatch.setattr(safe_fetch.SafeClient, "get", rec_get)
    monkeypatch.setattr(safe_fetch, "fetch_validated", rec_fv)
    explorer.FETCH_CACHE.clear()
    explorer.PDF_CACHE.clear()
    explorer._host_slow_hits.clear()
    explorer.RENDER_CACHE.clear()
    yield rec
    explorer.FETCH_CACHE.clear()
    explorer.PDF_CACHE.clear()


def _trail():
    return SimpleNamespace(notes=[])


# ------------------------------------------------- loopback refused, all paths

def test_flag_on_refuses_loopback_everywhere(safe_on, local_server):
    rec = safe_on
    page = local_server + "/page"
    pdf = local_server + "/fees.pdf"

    def used_safe(fn, expect):
        before = len(rec["safe"])
        assert fn() == expect
        assert len(rec["safe"]) > before, "safe path not used"

    used_safe(lambda: fetcher.PageCache().get_html(page), None)
    used_safe(lambda: fetcher.PageCache().get(page), None)
    used_safe(lambda: explorer.fetch_page_text_and_html(page), (None, None))
    used_safe(lambda: http_fetch.fetch_html(page), None)
    used_safe(lambda: abstract_classifier._default_fetcher(page), None)
    used_safe(lambda: abstract_classifier._default_fetcher(pdf), None)
    used_safe(lambda: explorer._fetch_document_text(pdf, _trail()), None)
    assert explorer._fetch_document_text(local_server + "/fees.docx", _trail()) is None
    assert vision.fetch_image_as_data_url(local_server + "/img.png") is None
    assert explorer.render_page(page) == (None, None, [])
    assert fetcher.PageCache()._fetch_browser(page) is None
    assert rec["hits"] == []  # plain client / httpx.get / Playwright never reached
    assert _Handler.hits == []  # nothing ever reached the server


def test_cfp_pdf_parsed_in_subprocess(safe_on, monkeypatch):
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, *a, **k: ("ok", url, b"%PDF-1.4 x", "utf-8", 200))
    calls = []

    def fake_run(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout=b"Abstract deadline 1 May 2027\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(abstract_classifier, "pdf_bytes_to_text",
                        lambda *a, **k: pytest.fail("in-process pypdf used"))
    got = abstract_classifier._default_fetcher("https://example.org/cfp.pdf")
    assert got == ("pdf", "Abstract deadline 1 May 2027")
    assert calls[0][0][0] == sys.executable and calls[0][1]["timeout"] == 20
    assert "SUPABASE_KEY" not in calls[0][1]["env"]
    # non-PDF bytes are never parsed
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, *a, **k: ("ok", url, b"<html>", "utf-8", 200))
    assert abstract_classifier._default_fetcher("https://example.org/cfp.pdf") is None
    assert len(calls) == 1


def test_slow_drip_cut_off_by_deadline(monkeypatch):
    _dns(monkeypatch, {"example.org": PUBLIC})
    clock = {"t": 1000.0}
    monkeypatch.setattr(safe_fetch.time, "monotonic", lambda: clock["t"])

    class Drip(httpx.SyncByteStream):
        def __iter__(self):
            while True:
                clock["t"] += 5  # each byte takes 5 virtual seconds
                yield b"x"

    client = _RealClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, stream=Drip())), follow_redirects=False)
    v, *_ = safe_fetch.fetch_validated("https://example.org/", client=client,
                                       deadline=clock["t"] + 20)
    assert v == "timeout"


def test_safeclient_passes_deadline(monkeypatch):
    seen = {}
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, chk, **k: seen.update(k) or ("ok", url, b"", "utf-8", 200))
    safe_fetch.SafeClient(timeout=300).get("https://example.org/")
    import time
    assert 0 < seen["deadline"] - time.monotonic() <= 20.5


@pytest.mark.parametrize("enc", ["gzip", "br", "zstd", "deflate", "x-gzip"])
def test_content_encoding_refused_without_reading_body(monkeypatch, enc):
    _dns(monkeypatch, {"example.org": PUBLIC})
    read = []

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            read.append(1)
            yield b"bomb"

    seen_hdr = []

    def handler(req):
        seen_hdr.append(req.headers.get("accept-encoding"))
        return httpx.Response(200, headers={"content-encoding": enc}, stream=Body())

    client = _RealClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    v, *_ = safe_fetch.fetch_validated("https://example.org/", client=client)
    assert v == "encoding_refused" and read == []
    assert seen_hdr == ["identity"]


def test_encoding_refusal_independent_of_installed_decoders(monkeypatch):
    """Proof for CI (zstandard is an unpinned transitive dep): refusal must
    not rely on httpx having, or lacking, a decoder for the encoding."""
    import httpx._decoders as dec
    _dns(monkeypatch, {"example.org": PUBLIC})

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("decoder used")

    # Mutate the shared dict in place: httpx._models holds the same object.
    for k in ("gzip", "deflate", "br", "zstd"):
        monkeypatch.setitem(dec.SUPPORTED_DECODERS, k, Boom)
    # Prove the patch is live before relying on it.
    with pytest.raises(AssertionError, match="decoder used"):
        httpx.Response(200, headers={"content-encoding": "zstd"}, content=b"x").read()
    read = []

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            read.append(1)
            yield b"bomb"

    client = _RealClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-encoding": "zstd"}, stream=Body())),
        follow_redirects=False)
    v, *_ = safe_fetch.fetch_validated("https://example.org/", client=client)
    assert v == "encoding_refused" and read == []


def test_accept_encoding_identity_on_every_hop(monkeypatch):
    _dns(monkeypatch, {"example.org": PUBLIC})
    seen = []

    def handler(req):
        seen.append((req.url.path, req.headers.get("accept-encoding")))
        if req.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://example.org/b"})
        return httpx.Response(200, content=b"ok")

    client = _RealClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    v, *_ = safe_fetch.fetch_validated("https://example.org/a", client=client)
    assert v == "ok"
    assert seen == [("/a", "identity"), ("/b", "identity")]


# --------------------------------------------------- redirect to internal host

def _dns(monkeypatch, mapping):
    def fake(host, *a, **k):
        return mapping[host]
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fake)


PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_redirect_to_metadata_address_is_refused(monkeypatch):
    _dns(monkeypatch, {"example.org": PUBLIC})

    def handler(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    client = _RealClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    verdict, hop, *_ = safe_fetch.fetch_validated("https://example.org/", client=client)
    assert verdict == "rejected" and "169.254.169.254" in hop

    # SafeClient (the drop-in used by the fetchers) turns a refusal into ConnectError.
    monkeypatch.setattr(httpx, "Client", lambda **k: _RealClient(
        transport=httpx.MockTransport(handler), follow_redirects=False))
    with pytest.raises(httpx.ConnectError):
        safe_fetch.SafeClient().get("https://example.org/")


def test_size_cap_cuts_off_stream(monkeypatch):
    _dns(monkeypatch, {"example.org": PUBLIC})
    big = b"x" * (3 * 1024 * 1024)
    client = _RealClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=big)),
                         follow_redirects=False)
    v, _f, body, *_ = safe_fetch.fetch_validated("https://example.org/", client=client, max_bytes=1000)
    assert v == "ok" and len(body) <= 1000


def test_oversize_pdf_is_skipped(safe_on, monkeypatch):
    from remediator.pdf_text import PDF_MAX_BYTES
    seen = {}

    def fake_fv(url, url_check=None, **kw):
        seen.update(kw)
        return "ok", url, b"%PDF" + b"0" * PDF_MAX_BYTES, "utf-8", 200

    monkeypatch.setattr(safe_fetch, "fetch_validated", fake_fv)
    tr = _trail()
    assert explorer._fetch_document_text("https://example.org/a.pdf", tr) is None
    assert seen["max_bytes"] == PDF_MAX_BYTES + 1  # cap enforced while streaming
    assert any("too_large" in n for n in tr.notes)


# ------------------------------------------------------------ PDF subprocess

def test_pdf_parsed_in_subprocess(safe_on, monkeypatch):
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, *a, **k: ("ok", url, b"%PDF-1.4 fake", "utf-8", 200))
    calls = []

    def fake_run(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout=b"Member  450\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    text = explorer._fetch_document_text("https://example.org/fees.pdf", _trail())
    assert text == "Member 450"
    args, kw = calls[0]
    assert args[0] == sys.executable and args[1] == "-c"
    assert kw["timeout"] == 20 and kw["input"] == b"%PDF-1.4 fake"
    assert args[-1] == "20"  # page cap


def test_docx_skipped_in_safe_mode(safe_on, monkeypatch):
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda *a, **k: pytest.fail("docx must not be fetched"))
    tr = _trail()
    assert explorer._fetch_document_text("https://example.org/fees.docx", tr) is None
    assert any("docx_skipped" in n for n in tr.notes)


def test_non_pdf_bytes_not_parsed(safe_on, monkeypatch):
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, *a, **k: ("ok", url, b"PK\x03\x04zip", "utf-8", 200))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no parse"))
    assert explorer._fetch_document_text("https://example.org/x.pdf", _trail()) is None


def test_isolated_parser_survives_garbage():
    assert pdf_text.pdf_to_text_isolated(b"not a pdf at all") == ""


def test_isolated_parser_garbage_is_loud(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert pdf_text.pdf_to_text_isolated(b"not a pdf at all") == ""
    msgs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("pdf_text:")]
    assert msgs and "pdf_child_error" in msgs[0]


def test_marker_survives_stderr_noise_and_is_escaped(monkeypatch, caplog):
    import logging
    noise = b"pypdf warning line\n" * 60  # > 1000 bytes before the marker
    monkeypatch.setattr(subprocess, "run", lambda a, **k: subprocess.CompletedProcess(
        a, 3, stdout=b"", stderr=noise + b"pdf_child_error:PdfReadError"))
    with caplog.at_level(logging.WARNING):
        assert pdf_text.pdf_to_text_isolated(b"%PDF-1.4 x") == ""
    msg = [r.getMessage() for r in caplog.records if r.getMessage().startswith("pdf_text:")][0]
    assert "pdf_child_error:PdfReadError" in msg
    # PDF-influenced stderr with no marker: last 200 chars, escaped, single line
    monkeypatch.setattr(subprocess, "run", lambda a, **k: subprocess.CompletedProcess(
        a, 3, stdout=b"", stderr=b"::error::x\nsecond line"))
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        pdf_text.pdf_to_text_isolated(b"%PDF-1.4 x")
    msg = caplog.records[-1].getMessage()
    assert "\n" not in msg and "\\n" in msg


def test_isolated_parser_corrupt_pdf_is_loud(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert pdf_text.pdf_to_text_isolated(b"%PDF-1.4\n1 0 obj<<>>endobj garbage") == ""
    assert any(r.getMessage().startswith("pdf_text:") and
               ("pdf_child_error" in r.getMessage() or "no text" in r.getMessage())
               for r in caplog.records)


def test_isolated_parser_no_text_warns(monkeypatch, caplog):
    import logging
    monkeypatch.setattr(subprocess, "run", lambda a, **k: subprocess.CompletedProcess(
        a, 0, stdout=b"", stderr=b"noise " * 200 + b"pdf_child_pages_failed:2"))
    with caplog.at_level(logging.WARNING):
        assert pdf_text.pdf_to_text_isolated(b"%PDF-1.4 x") == ""
    assert any("produced no text" in r.getMessage() and "pdf_child_pages_failed:2" in r.getMessage()
               for r in caplog.records)


def test_classifier_non_pdf_bytes_warns(safe_on, monkeypatch, caplog):
    import logging
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, *a, **k: ("ok", url, b"<html>", None, 200))
    with caplog.at_level(logging.WARNING):
        assert abstract_classifier._default_fetcher("https://example.org/cfp.pdf") is None
    assert any("not a PDF" in r.getMessage() for r in caplog.records)


def test_explorer_pdf_no_text_noted(safe_on, monkeypatch):
    monkeypatch.setattr(safe_fetch, "fetch_validated",
                        lambda url, *a, **k: ("ok", url, b"%PDF-1.4 x", None, 200))
    monkeypatch.setattr(subprocess, "run", lambda a, **k: subprocess.CompletedProcess(
        a, 0, stdout=b"", stderr=b""))
    tr = _trail()
    assert explorer._fetch_document_text("https://example.org/scan.pdf", tr) == ""
    assert any(n.startswith("pdf_no_text:") for n in tr.notes)


# ------------------------------------------------------- inline images (vision)

DATA_URL = "data:image/png;base64,iVBORw0KGgo="


@pytest.fixture
def vision_rec(monkeypatch):
    calls = []

    def recorder(*a, **k):
        calls.append((a, k))
        msg = SimpleNamespace(content='{"tiers": []}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(vision, "_client_get", lambda: object())
    monkeypatch.setattr(vision, "chat_completion", recorder)
    return calls


def test_extract_json_drops_data_urls_in_safe_mode(safe_on, vision_rec, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert vision.extract_json([DATA_URL], "p") is None
    assert vision_rec == []
    assert sum("inline image(s) dropped" in r.getMessage() for r in caplog.records) == 1


def test_extract_pricing_from_images_off_in_safe_mode(safe_on, vision_rec):
    assert vision.extract_pricing_from_images([DATA_URL]) == []
    assert vision_rec == []


def test_extract_json_data_url_reaches_model_flag_off(monkeypatch, vision_rec):
    monkeypatch.delenv("REMEDIATOR_SAFE_FETCH", raising=False)
    assert vision.extract_json([DATA_URL], "p") == {"tiers": []}
    assert len(vision_rec) == 1
    sent = vision_rec[0][1]["messages"][0]["content"]
    assert any(c.get("image_url", {}).get("url") == DATA_URL for c in sent)


# ------------------------------------------------------------- write policy

def test_url_patches_allowed_helper():
    assert runner._url_patches_allowed({"source_id": 5}) is True
    assert runner._url_patches_allowed({"source_id": 1000}) is False
    assert runner._url_patches_allowed({}, 1000) is False
    assert runner._url_patches_allowed({}, 5) is True


class _Q:
    def __init__(self, sb, name):
        self.sb, self.name, self.op, self.payload = sb, name, "select", None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def range(self, *a, **k): return self
    def delete(self): self.op = "delete"; return self
    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def update(self, d): self.op, self.payload = "update", d; return self

    def execute(self):
        if self.op != "select":
            self.sb.writes.append((self.name, self.op, self.payload))
        if self.op == "update":
            return SimpleNamespace(data=[self.payload])  # non-empty: row unchanged since read
        return SimpleNamespace(data=self.sb.data.get(self.name, []) if self.op == "select" else [])


class _Rpc:
    def __init__(self, sb, name, params):
        self.sb, self.name, self.params = sb, name, params

    def execute(self):
        self.sb.writes.append(("rpc", self.name, self.params))
        return SimpleNamespace(data=1)


class _SB:
    def __init__(self, data):
        self.data, self.writes = data, []

    def table(self, name): return _Q(self, name)
    def rpc(self, name, params=None): return _Rpc(self, name, params)


class _FakeCache:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, u): return "page text"
    def get_html(self, u): return "<html></html>"


def _run(monkeypatch, sid, found):
    row = {"id": 1, "source_id": sid, "source_url": "https://e.org/x", "conference_name": "X",
           "organiser_url": None, "booking_url": None}
    sb = _SB({"scraper_sources": [{"id": sid, "society": "S", "source_name": "n"}],
              "conferences": [row]})
    tier = {"tier_label": "Member", "price_gbp": 100, "currency": "GBP"}
    result = SimpleNamespace(
        found=found, value=[tier] if found else None, method="text",
        external_url="https://evil.example/reg", extras={},
        audit_trail=SimpleNamespace(subpages_fetched=[]),
        to_dict=lambda: {})
    monkeypatch.setattr(runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(runner, "PageCache", _FakeCache)
    monkeypatch.setattr(runner, "FIXERS", {})
    monkeypatch.setattr(runner, "EXPLORERS", {"pricing": lambda **kw: result})
    monkeypatch.setattr(runner, "validate", lambda f, v: True)
    monkeypatch.setattr(runner, "detect_gaps_for_rows", lambda c, p: [(r, ["pricing"]) for r in c])
    monkeypatch.setattr(runner, "get_promoted_patterns", lambda *a, **k: [])
    monkeypatch.setattr(runner, "record_success", lambda *a, **k: None)
    monkeypatch.setattr(runner, "close_render_browser", lambda: None)
    monkeypatch.setattr(runner, "write_report", lambda **k: "report.json")
    runner.remediate_source(sid)
    return [w for w in sb.writes if w[0] == "conferences" and w[1] == "update"
            and set(w[2]) & {"organiser_url", "booking_url", "source_url"}]


@pytest.mark.parametrize("found", [True, False])
def test_source_1000_never_gets_url_patches(monkeypatch, found):
    assert _run(monkeypatch, 1000, found) == []


def test_other_sources_still_get_url_patches(monkeypatch):
    urls = _run(monkeypatch, 5, True)
    assert {k for w in urls for k in w[2]} == {"organiser_url", "booking_url"}
    assert _run(monkeypatch, 5, False)  # no-fees path records organiser_url


# ------------------------------------------------------------------ flag off

def test_flag_off_leaves_real_httpx(monkeypatch):
    monkeypatch.delenv("REMEDIATOR_SAFE_FETCH", raising=False)
    assert safe_fetch.enabled() is False
    for mod in (fetcher, explorer, http_fetch):
        assert mod.httpx is httpx
    assert httpx.Client is _RealClient
    assert callable(httpx.get) and httpx.get.__module__.startswith("httpx")
    # Flag-off client choice is the plain httpx client.
    monkeypatch.setattr(safe_fetch, "SafeClient", lambda **k: pytest.fail("safe client used"))
    monkeypatch.setattr(httpx, "Client", lambda **k: (_ for _ in ()).throw(RuntimeError("plain")))
    assert explorer.fetch_page_text_and_html("https://example.org/zz-flagoff") == (None, None)
    explorer.FETCH_CACHE.pop("https://example.org/zz-flagoff", None)
    explorer._host_slow_hits.pop("example.org", None)
