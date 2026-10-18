"""safe_fetch.py - SSRF-hardened fetching for untrusted (user-submitted) URLs.

Shared by enrich_submissions.py and, when REMEDIATOR_SAFE_FETCH=1, by the
remediator (PageCache._fetch_httpx, explorer fetches, call-for-papers follow).
With the flag unset nothing here is used by the remediator.

Guarantees: http/https only; every redirect hop is address-checked (no IP
literals, loopback, private, link-local, reserved); no blind redirect
following; body capped at 2 MB; wall-clock deadline honoured while streaming;
no browser. Residual DNS rebinding between check and connect is accepted.
"""

import html as _html
import ipaddress
import os
import re
import socket
import time
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx


def _ip_is_blocked(ip: "ipaddress._BaseAddress") -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # not is_global covers loopback, RFC1918, link-local, 0.0.0.0/8, CGNAT,
    # fc00::/7, fe80::/10, ::1, reserved ranges.
    return (not ip.is_global) or ip.is_multicast or ip.is_unspecified


def check_url_safe(url: Optional[str]) -> tuple:
    """Return (ok, reason). Never fetches anything itself."""
    if not url or not isinstance(url, str):
        return False, "no url"
    try:
        p = urlparse(url.strip())
    except Exception:
        return False, "unparseable url"
    if p.scheme not in ("http", "https"):
        return False, "scheme not http/https"
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False, "no hostname"
    if host == "localhost" or host.endswith(".localhost"):
        return False, "localhost"
    try:
        ipaddress.ip_address(host)
        return False, "ip literal"
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except Exception:
        return False, "unresolvable host"
    if not infos:
        return False, "unresolvable host"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False, "bad address"
        if _ip_is_blocked(ip):
            return False, "non-public address"
    return True, ""


_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_UA = "Mozilla/5.0 (compatible; MedConfBot/1.0; +enrichment)"


MAX_BODY_BYTES = 2 * 1024 * 1024
_DROP_TAG_RE = re.compile(r"(script|style|noscript)(?![a-z0-9])")


def html_to_text(html: str) -> str:
    """Same output as remediator.fetcher.PageCache._fetch_httpx, but a single
    linear pass (no regex backtracking on hostile input). Input capped at 2 MB.
    script/style/noscript bodies are dropped (JSON-LD kept); an unclosed
    opener drops the rest, as browsers do."""
    html = html[:MAX_BODY_BYTES]
    low = html.lower()
    n, i, out = len(html), 0, []
    while i < n:
        j = html.find("<", i)
        if j < 0:
            out.append(html[i:])
            break
        out.append(html[i:j])
        k = html.find(">", j)
        if k < 0:
            break
        tag = low[j + 1:k]
        m = _DROP_TAG_RE.match(tag)
        if m and "ld+json" not in tag:
            close = low.find("</" + m.group(1), k)
            if close < 0:
                break
            k2 = html.find(">", close)
            out.append(" ")
            i = n if k2 < 0 else k2 + 1
            continue
        out.append(" ")
        i = k + 1
    t = _html.unescape("".join(out))
    return re.sub(r"\s+", " ", t).strip()[:200000]


def pin_address(host: str, port: int) -> Optional[str]:
    """Resolve once and return the first allowed address (None if none is)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception:
        return None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            continue
        if not _ip_is_blocked(ip):
            return str(ip)
    return None


def _pinned_request(url: str) -> Optional[tuple]:
    """(pinned_url, headers, extensions): connect to the validated IP while
    keeping the hostname for Host header, SNI and certificate verification."""
    p = urlparse(url)
    host = p.hostname or ""
    port = p.port or (443 if p.scheme == "https" else 80)
    ip = pin_address(host, port)
    if ip is None:
        return None
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_host}:{p.port}" if p.port else ip_host
    pinned = p._replace(netloc=netloc).geturl()
    host_hdr = f"{host}:{p.port}" if p.port else host
    return pinned, {"Host": host_hdr}, {"sni_hostname": host}


def fetch_validated(url: str, url_check: Callable = check_url_safe, max_hops: int = 5,
                    client: Optional[httpx.Client] = None,
                    deadline: Optional[float] = None,
                    max_bytes: int = MAX_BODY_BYTES,
                    pin: Optional[bool] = None) -> tuple:
    """GET hop by hop (no automatic redirects), SSRF-checking every hop.

    Returns (verdict, final_url, body_bytes, encoding, status):
      ok        final 2xx response, body capped at max_bytes
      blocked   final response was not 2xx (status says which)
      rejected  a hop failed the check / too many hops / transport error
      timeout   monotonic `deadline` passed (slow-drip server)
    """
    # DNS-rebinding defence: connect to the address we validated (pin=True).
    # Default: on whenever the real address check is in use.
    if pin is None:
        pin = url_check is check_url_safe
    own = client is None
    if own:
        client = httpx.Client(follow_redirects=False,
                              timeout=httpx.Timeout(connect=10, read=15, write=10, pool=10),
                              headers={"User-Agent": _UA})
    try:
        current = url
        for hop in range(max_hops + 1):
            if deadline is not None and time.monotonic() > deadline:
                return "timeout", current, b"", "utf-8", 0
            if not url_check(current)[0]:
                return "rejected", current, b"", "utf-8", 0
            target, hdrs, exts = current, None, None
            if pin:
                pr = _pinned_request(current)
                if pr is None:
                    return "rejected", current, b"", "utf-8", 0
                target, hdrs, exts = pr
            with client.stream("GET", target, headers=hdrs, extensions=exts) as r:
                location = r.headers.get("location")
                if r.status_code in _REDIRECT_STATUSES and location:
                    if hop >= max_hops:
                        break
                    current = urljoin(current, location)
                    continue
                if not 200 <= r.status_code < 300:
                    return "blocked", current, b"", "utf-8", r.status_code
                body = bytearray()
                for chunk in r.iter_bytes():
                    if deadline is not None and time.monotonic() > deadline:
                        return "timeout", current, b"", "utf-8", 0
                    body.extend(chunk)
                    if len(body) >= max_bytes:
                        break
                enc = r.encoding or "utf-8"
                status = r.status_code
            return "ok", current, bytes(body[:max_bytes]), enc, status
        return "rejected", "too many redirects", b"", "utf-8", 0
    except Exception as e:  # noqa: BLE001
        return "rejected", f"fetch failed: {type(e).__name__}", b"", "utf-8", 0
    finally:
        if own:
            client.close()


def resolve_redirect_chain(url: str, url_check: Callable, max_hops: int = 5,
                           client: Optional[httpx.Client] = None,
                           deadline: Optional[float] = None,
                           pin: Optional[bool] = None) -> tuple:
    """Return (verdict, final_url, html) - see fetch_validated for verdicts.
    The body comes from this validated response; callers must never re-fetch."""
    verdict, final, body, enc, _ = fetch_validated(url, url_check, max_hops, client, deadline, pin=pin)
    if verdict != "ok":
        return verdict, final, ""
    return "ok", final, body.decode(enc, errors="replace")


# ------------------------------------------------- remediator safe-fetch mode

def enabled() -> bool:
    """True when REMEDIATOR_SAFE_FETCH=1 (community source 1000 job only)."""
    return os.environ.get("REMEDIATOR_SAFE_FETCH") == "1"


def fetch_text_html(url: str, **_ignored) -> tuple:
    """(text, html) from a hop-validated fetch, or (None, None)."""
    verdict, _final, html = resolve_redirect_chain(url, check_url_safe)
    if verdict != "ok":
        return None, None
    return html_to_text(html), html


class SafeClient:
    """Drop-in for the `with httpx.Client(...) as c: c.get(url)` pattern.
    Constructor kwargs (timeout, headers, follow_redirects) are accepted and
    ignored: redirects are always hop-validated, never followed blindly."""

    def __init__(self, max_bytes: int = MAX_BODY_BYTES, **_ignored):
        self.max_bytes = max_bytes

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def get(self, url: str) -> httpx.Response:
        verdict, final, body, _enc, status = fetch_validated(
            url, check_url_safe, max_bytes=self.max_bytes)
        req = httpx.Request("GET", final if verdict in ("ok", "blocked") else url)
        if verdict == "ok":
            return httpx.Response(status, content=body, request=req)
        if verdict == "blocked":
            return httpx.Response(status, request=req)
        raise httpx.ConnectError(f"safe-fetch refused: {verdict} {final}", request=req)


