"""robots.txt gate for sub-page discovery.

allowed(url)  -> False when the host's robots.txt disallows `url` for our user agent
                 (`*` rules plus the MedConfBot token and the browser-style UA string
                 http_fetch sends; a disallow under any of them blocks).
pace(url)     -> honours Crawl-delay per host (sleep, capped at CRAWL_DELAY_CAP).

robots.txt is fetched at most once per host per process (24 h TTL). A fetch error or a
non-200 answer means "allowed". Only http(s) URLs are gated.
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple
from urllib import robotparser
from urllib.parse import urlparse

from logger import logger

ROBOTS_TTL = 24 * 3600.0     # rationale: robots.txt rarely changes; a daily cron never needs fresher
CRAWL_DELAY_CAP = 10.0       # rationale: a hostile Crawl-delay must not stall a 20 s per-event clock
ROBOTS_TIMEOUT = 5.0
BOT_TOKEN = "MedConfBot"
_BROWSER_UA = "Mozilla/5.0 (compatible; MedConfBot)"

# origin -> (fetched_at, parser or None when allow-all)
_cache: Dict[str, Tuple[float, Optional[robotparser.RobotFileParser]]] = {}
_last_hit: Dict[str, float] = {}
_logged: set = set()


def _user_agents():
    uas = [BOT_TOKEN, _BROWSER_UA]
    try:
        from extractors import http_fetch
        ua = (getattr(http_fetch, "DEFAULT_HEADERS", {}) or {}).get("User-Agent")
        if ua and ua not in uas:
            uas.append(ua)
    except Exception:  # noqa: BLE001
        pass
    return uas


def _fetch_robots_text(origin: str) -> Optional[str]:
    """robots.txt body on a 200, else None. The only network seam (tests patch it)."""
    url = origin + "/robots.txt"
    try:
        import safe_fetch
        if safe_fetch.enabled():
            got = safe_fetch.fetch_validated(url, safe_fetch.check_url_safe, max_bytes=500_001,
                                             deadline=time.monotonic() + ROBOTS_TIMEOUT)
            if not got or got[0] != "ok" or (got[4] or 200) != 200:
                return None
            return got[2].decode("utf-8", errors="replace")
        import httpx
        with httpx.Client(timeout=ROBOTS_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": _BROWSER_UA}) as c:
            r = c.get(url)
            if r.status_code != 200 or len(r.content) > 500_000:
                return None
            return r.text
    except Exception as e:  # noqa: BLE001
        logger.debug(f"robots_gate: fetch failed {url}: {type(e).__name__}")
        return None


def _origin(url: str) -> Optional[str]:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}".lower()


def _parser_for(origin: str) -> Optional[robotparser.RobotFileParser]:
    now = time.monotonic()
    hit = _cache.get(origin)
    if hit and now - hit[0] < ROBOTS_TTL:
        return hit[1]
    rp: Optional[robotparser.RobotFileParser] = None
    try:
        text = _fetch_robots_text(origin)
        if text:
            rp = robotparser.RobotFileParser()
            rp.parse(text.splitlines())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"robots_gate: parse failed {origin}: {type(e).__name__}")
        rp = None
    _cache[origin] = (now, rp)
    return rp


def allowed(url: str) -> bool:
    origin = _origin(url)
    if not origin:
        return True
    rp = _parser_for(origin)
    if rp is None:
        return True
    try:
        ok = all(rp.can_fetch(ua, url) for ua in _user_agents())
    except Exception:  # noqa: BLE001
        return True
    if not ok and url not in _logged:
        _logged.add(url)
        logger.info(f"discovery: robots disallows {url}")
    return ok


def pace(url: str) -> None:
    """Sleep so consecutive fetches to one host respect Crawl-delay (capped)."""
    origin = _origin(url)
    if not origin:
        return
    rp = _cache.get(origin, (0, None))[1]
    delay = None
    if rp is not None:
        for ua in _user_agents():
            try:
                d = rp.crawl_delay(ua)
            except Exception:  # noqa: BLE001
                d = None
            if d is not None:
                delay = max(delay or 0.0, float(d))
    if delay:
        delay = min(delay, CRAWL_DELAY_CAP)
        last = _last_hit.get(origin)
        if last is not None:
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
    _last_hit[origin] = time.monotonic()


def reset() -> None:
    _cache.clear()
    _last_hit.clear()
    _logged.clear()
