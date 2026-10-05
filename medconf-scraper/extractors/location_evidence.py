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
        h = _CHROME_RE.sub(" ", page_html)
        h = _BLOCK_TAG_RE.sub("\n", h)
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
