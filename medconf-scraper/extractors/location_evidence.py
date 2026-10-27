"""Evidence that an event page NAMES a city/venue (pure, no network).

Shared by the audit (city/venue checks) and the new-source coverage checks.
Site chrome (nav/header/footer/aside) is excluded so an organiser's footer
address never counts. Returns a short evidence string or None.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Optional

_CHROME_RE = re.compile(r"<(nav|header|footer|aside|script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', re.I | re.S)
_BLOCK_TAG_RE = re.compile(r"</?(?:p|li|ul|ol|div|br|h[1-6]|tr|td|th|section|article|dt|dd|span|strong|b)\b[^>]*>", re.I)
_NOT_PLACE_RE = re.compile(r"\b(?:online|virtual|zoom|webinar|teams|livestream|on[\s-]?demand|tba|tbc|tbd|to\s+be\s+(?:announced|confirmed))\b", re.I)
_FORM_LABEL_RE = re.compile(r"^(?:address|line\s*\d|city|state|zip|postcode|country|name|e-?mail|phone|select|choose|enter)\b|address\s+line", re.I)
_LABEL_RE = re.compile(r"^(?:location|venue|where|address|event\s+location)\s*:?\s*(.*)$", re.I)
_US_ADDR_RE = re.compile(r"[A-Z][A-Za-z.'\- ]{2,40},\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[A-Z][\w.'\- ]{2,40}\s+(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Place|Square)\b\.?,\s*[A-Z][\w .'\-]{2,40}")
_UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
_VENUE_KW_RE = re.compile(
    r"\b[A-Z][\w'&.\-]+(?:\s+[A-Z&][\w'&.\-]*)*\s+"
    r"(?:Convention\s+Cent(?:er|re)|Conference\s+Cent(?:er|re)|Exhibition\s+Cent(?:er|re)|Hotel|University|Hospital|Hall)\b")

_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
# "October 26 - 30, 2027" / "Feb 28 - Mar 3, 2027" / "June 1, 2027" (month first)
_DATE_RANGE = rf"{_MON}\s+\d{{1,2}}(?:\s*[-\u2013\u2014]\s*(?:{_MON}\s+)?\d{{1,2}})?,\s*20\d{{2}}"
_BANNER_DATE_RE = re.compile(rf"^{_DATE_RANGE}$")
# banner on ONE line: <date range> <Venue words> <City>, <State|Country>
_BANNER_LINE_RE = re.compile(
    rf"^{_DATE_RANGE}\s+(?P<rest>[A-Z][A-Za-z0-9&'.\- ]{{3,90}}?)\s*,\s*(?P<region>[A-Z][A-Za-z.'\- ]{{2,30}})$")
# "<Place words>, <Place words>": capitalised words only (a venue/city line)
_PLACE_PAIR_RE = re.compile(
    r"^[A-Z][A-Za-z0-9&'.\-]*(?: (?:[A-Z][A-Za-z0-9&'.\-]*|of|de|the|and|&|la|le|du|von|van))*"
    r",\s*[A-Z][A-Za-z.'\-]*(?: (?:[A-Z][A-Za-z.'\-]*|of|de|the|and|&))*$")
_NOT_PLACE_PAIR_RE = re.compile(
    r"\b(?:Dr|Prof|Professor|Consultant|Director|Chair|Chairman|President|Ltd|Limited|Inc|LLC|Registration|Abstract|Programme|Register)\b|\b(?:by|from)\b",
    re.I)
_H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1\s*>", re.I | re.S)


def _is_place_pair(line: str) -> bool:
    return (len(line) <= 90 and len(line.split()) <= 10 and not re.search(r"\d", line)
            and bool(_PLACE_PAIR_RE.match(line)) and not _NOT_PLACE_PAIR_RE.search(line)
            and not _NOT_PLACE_RE.search(line))


def _banner_evidence(lines) -> Optional[str]:
    """Date/venue banner under the event title: "October 26 - 30, 2027
    Sheraton Grand Chicago Riverwalk Chicago, Illinois" on one line, or the
    date on its own line followed by 1-2 place lines (spans/<br> rendering)."""
    for i, l in enumerate(lines):
        if len(l) <= 160:
            m = _BANNER_LINE_RE.match(l)
            if m and not _NOT_PLACE_RE.search(l) and not re.search(r"\d", m.group("rest")):
                return f"date/venue banner: {l[:120]}"
        if _BANNER_DATE_RE.match(l):
            nxt = lines[i + 1: i + 3]
            if nxt and _is_place_pair(nxt[-1]) and all(len(x) <= 90 and not re.search(r"\d{4}", x) for x in nxt):
                return f"date/venue banner: {l} {' '.join(nxt)}"[:140]
    return None


def _under_h1_evidence(h: str) -> Optional[str]:
    """"<Venue>, <City>" as the first line directly under the page's H1."""
    m = _H1_RE.search(h)
    if not m:
        return None
    tail = _BLOCK_TAG_RE.sub("\n", h[m.end():m.end() + 1500])
    for l in tail.split("\n"):
        l = re.sub(r"[ \t\r\xa0]+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", l))).strip()
        if not l:
            continue
        return f"line under h1: {l[:100]}" if _is_place_pair(l) else None
    return None


def _ld_places(node: Any):
    if isinstance(node, list):
        for n in node:
            yield from _ld_places(n)
    elif isinstance(node, dict):
        if "location" in node:
            loc = node["location"]
            for l in (loc if isinstance(loc, list) else [loc]):
                yield l
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _ld_places(v)


def _from_json_ld(html: str) -> Optional[str]:
    for m in _LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for loc in _ld_places(data):
            if isinstance(loc, str):
                if loc.strip() and not _NOT_PLACE_RE.search(loc):
                    return f"JSON-LD location: {loc[:100]}"
                continue
            if not isinstance(loc, dict) or "VirtualLocation" in str(loc.get("@type")):
                continue
            addr = loc.get("address")
            city = addr.get("addressLocality") if isinstance(addr, dict) else (addr if isinstance(addr, str) else None)
            name = loc.get("name")
            val = ", ".join(str(x) for x in (name, city) if x)
            if val and not _NOT_PLACE_RE.search(val):
                return f"JSON-LD location: {val[:100]}"
    return None


def find_location_evidence(page_html: str, page_text: str = "") -> Optional[str]:
    ld = _from_json_ld(page_html or "")
    if ld:
        return ld
    if page_html:
        h_raw = _CHROME_RE.sub(" ", page_html)
        h = _BLOCK_TAG_RE.sub("\n", h_raw)
        text = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    else:
        text = page_text or ""
    lines = [re.sub(r"[ \t\r\xa0]+", " ", l).strip() for l in text.split("\n")]
    lines = [l for l in lines if l]

    # labelled lines (value inline or on the next line)
    for i, l in enumerate(lines):
        m = _LABEL_RE.match(l)
        if not m:
            continue
        val = m.group(1).strip()
        if not val and i + 1 < len(lines):
            val = lines[i + 1]
        if val and re.search(r"[A-Za-z]{3}", val) and not _FORM_LABEL_RE.search(val) and not _NOT_PLACE_RE.search(val) and len(val) <= 160:
            return f"labelled line: {l[:60]} {val[:100]}".strip()

    ban = _banner_evidence(lines)
    if ban:
        return ban
    if page_html:
        h1 = _under_h1_evidence(h_raw)
        if h1:
            return h1

    for l in lines:
        if len(l) > 200:
            continue
        m = _US_ADDR_RE.search(l) or _STREET_RE.search(l)
        if m:
            return f"address block: {m.group(0)[:100]}"
        m = _UK_POSTCODE_RE.search(l)
        if m and re.search(r"[A-Za-z]{3,}.*,", l[: m.start()]):
            return f"address block: {l[:100]}"
    for l in lines:
        if len(l) <= 110 and len(l.split()) <= 14 and not _NOT_PLACE_RE.search(l):
            m = _VENUE_KW_RE.search(l)
            if m:
                return f"venue line: {m.group(0)[:100]}"
    return None
