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
import re
from urllib.parse import unquote, urlparse

from logger import logger

ROBOTS_TTL = 24 * 3600.0     # rationale: robots.txt rarely changes; a daily cron never needs fresher
CRAWL_DELAY_CAP = 10.0       # rationale: a hostile Crawl-delay must not stall a 20 s per-event clock
ROBOTS_TIMEOUT = 5.0
MAX_RULE_LEN = 1024      # longer rules are skipped
MAX_WILDCARDS = 10       # rules with more '*' are skipped
MAX_PATH_LEN = 2048      # longer paths match no rule
BOT_TOKEN = "MedConfBot"
_BROWSER_UA = "Mozilla/5.0 (compatible; MedConfBot)"

# origin -> (fetched_at, parser or None when allow-all)
_cache: Dict[str, Tuple[float, Optional['_Rules']]] = {}
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


class _Rules:
    """Parsed robots.txt with Google semantics: per-agent groups (most specific wins,
    else `*`), `*` wildcard, `$` end anchor, longest match wins, Allow beats Disallow on a
    tie, percent-decoded paths, query string part of the path."""

    def __init__(self, text: str):
        self.groups = []     # (agents[list lower], rules[(allow, regex, length)], delay)
        agents, rules, delay, in_rules = [], [], None, False
        def flush():
            if agents:
                self.groups.append((list(agents), list(rules), delay))
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "user-agent":
                if in_rules:
                    flush()
                    agents, rules, delay, in_rules = [], [], None, False
                agents.append(v.lower())
            elif k in ("allow", "disallow") and agents:
                in_rules = True
                spec = self._rx(v) if v else None   # empty Disallow allows everything; empty Allow is a no-op
                if spec is not None:
                    rules.append((k == "allow", spec, len(v)))
            elif k == "crawl-delay" and agents:
                in_rules = True
                try:
                    delay = float(v)
                except ValueError:
                    pass
        flush()

    @staticmethod
    def _rx(pattern: str):
        """Linear matcher spec (pieces, anchored_end) or None to skip a hostile rule."""
        pattern = unquote(pattern)
        if len(pattern) > MAX_RULE_LEN or pattern.count("*") > MAX_WILDCARDS:
            return None
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        pattern = re.sub(r"\*+", "*", pattern)
        return pattern.split("*"), anchored

    @staticmethod
    def _match(spec, path: str) -> bool:
        pieces, anchored = spec
        if len(pieces) == 1:
            return path == pieces[0] if anchored else path.startswith(pieces[0])
        if not path.startswith(pieces[0]):
            return False
        pos = len(pieces[0])
        for piece in pieces[1:-1]:
            if not piece:
                continue
            i = path.find(piece, pos)
            if i < 0:
                return False
            pos = i + len(piece)
        last = pieces[-1]
        if anchored:
            return path.endswith(last) and len(path) - len(last) >= pos
        return path.find(last, pos) >= 0

    def _select(self, uas):
        low = [u.lower() for u in uas]
        named = [g for g in self.groups if any(a != "*" and a and any(a in u for u in low) for a in g[0])]
        return named or [g for g in self.groups if "*" in g[0]]

    def can_fetch(self, uas, url: str) -> bool:
        p = urlparse(url)
        path = unquote((p.path or "/") + (("?" + p.query) if p.query else ""))
        if len(path) > MAX_PATH_LEN:
            return True          # too long for any rule to be matched safely
        best_len, best_allow = -1, True
        for _a, rules, _d in self._select(uas):
            for allow, rx, ln in rules:
                if self._match(rx, path) and (ln > best_len or (ln == best_len and allow)):
                    best_len, best_allow = ln, allow
        return best_allow

    def crawl_delay(self, uas):
        ds = [g[2] for g in self._select(uas) if g[2] is not None]
        return max(ds) if ds else None


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


def _parser_for(origin: str) -> Optional['_Rules']:
    now = time.monotonic()
    hit = _cache.get(origin)
    if hit and now - hit[0] < ROBOTS_TTL:
        return hit[1]
    rp: Optional['_Rules'] = None
    try:
        text = _fetch_robots_text(origin)
        if text:
            rp = _Rules(text)
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
        ok = rp.can_fetch(_user_agents(), url)
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
        try:
            delay = rp.crawl_delay(_user_agents())
        except Exception:  # noqa: BLE001
            delay = None
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
