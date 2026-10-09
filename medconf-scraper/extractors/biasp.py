"""BIASP (British and Irish Association of Stroke Physicians) events: one free-form WordPress page.

`https://biasp.org/events/` is a single Elementor page, not an archive: a dozen blocks of
`Title / Date(s): ... / Location: ... / CLICK HERE ... (Fitwise or organiser link)`, mixing BIASP's own
meetings (UK Stroke Forum) with third-party stroke events (World Stroke Congress, ESOC). There are no
per-event pages, so each block becomes a shell keyed by `/events/#<slug>` and the detail comes from the
block itself (the scraper's page load of the external booking link is ignored). Dates are often
year-less ("13 October"): the next occurrence on or after today is used. Fees are never on the page; the
registration link (outlook safelinks unwrapped) is kept as `organiser_url` for the fee explorer.
Un-labelled promo banners at the top (e.g. the free IMT careers webinar) carry no event title and are skipped.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .wordpress_generic import _COUNTRIES, classify_event_type, clip_venue, pick_event_dates

_URL = "https://biasp.org/events/"
_MONTHS = ("January February March April May June July August September October November December").split()
_LABEL_DATE_RE = re.compile(r"^Dates?\s*\(?s?\)?\s*\(?s?\)?\s*:?\s*(.*)$", re.I)
_LABEL_LOC_RE = re.compile(r"^Location\s*:?\s*(.*)$", re.I)
_YEARLESS_RE = re.compile(r"^(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s+([A-Z][a-z]+)\b")
_VENUE_KW_RE = re.compile(r"centre|center|hotel|hydro|university|institution|hospital|park|college|hall|regus|house|forum|lido", re.I)
_BLOCK_END_RE = re.compile(r"^(?:contact us|send|membership discount|association of british)\b", re.I)
_JUNK_TITLE_RE = re.compile(r"click here|register|^\W*$|^⟦|^for (?:the|more|information)|^to (?:view|register)|save the date|^date|^location", re.I)


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60]


def _unwrap(href: str) -> str:
    """Outlook safelinks wrapper -> the real target."""
    href = _html.unescape(href)
    if "safelinks.protection.outlook.com" in href:
        try:
            return parse_qs(urlparse(href).query).get("url", [href])[0]
        except Exception:  # noqa: BLE001
            return href
    return href


def _lines(html: str) -> List[str]:
    h = re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer)\b.*?</\1\s*>", " ", html)
    h = re.sub(r"""(?is)<a\b[^>]*?href=["']([^"']+)["'][^>]*>""", lambda m: f" ⟦{m.group(1)}⟧ ", h)
    h = re.sub(r"(?i)<(?:br|/p|/div|/h\d|/li|/tr|/td|/section)[^>]*>", "\n", h)
    h = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    return [re.sub(r"[ \t ]+", " ", l).strip() for l in h.split("\n") if l.strip()]


def _parse_dates(txt: str, today: date) -> Optional[tuple]:
    d = pick_event_dates(txt)
    if d:
        return d
    m = _YEARLESS_RE.match(txt.strip())                       # "13 October, 08:30 - 1700"
    if m and m.group(3) in _MONTHS:
        mon = _MONTHS.index(m.group(3)) + 1
        d1, d2 = int(m.group(1)), int(m.group(2) or m.group(1))
        y = today.year
        try:
            if date(y, mon, d2) < today:
                y += 1
            return date(y, mon, d1).isoformat(), date(y, mon, d2).isoformat()
        except ValueError:
            return None
    return None


class BiaspExtractor(BaseExtractor):
    SOCIETY = "BIASP"

    def __init__(self, source: Dict[str, Any]):
        super().__init__(source)

    def _fetch(self, url: str) -> Optional[str]:
        body = fetch_html(url, browser=getattr(self, "browser", None))
        if body and "Date(s)" in body or body and len(body) > 100000:
            return body
        page = getattr(getattr(self, "browser", None), "page", None)
        for attempt in range(3):
            if page is not None:
                try:
                    page.goto(url, wait_until="load", timeout=30000)
                    body = page.content()
                    if body and len(body) > 50000:
                        return body
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"BIASP fetch attempt {attempt + 1}/3 failed: {e}")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(_URL)
        if not html:
            return None
        L = _lines(html)
        today = date.today()
        labels = [i for i, l in enumerate(L) if _LABEL_DATE_RE.match(l) and re.match(r"^dates?\s*\(", l, re.I)]
        end_page = next((i for i in range(labels[-1], len(L)) if _BLOCK_END_RE.match(L[i])), len(L)) if labels else len(L)
        shells: List[Dict[str, Any]] = []
        seen = set()
        for n, i in enumerate(labels):
            title = next((L[k] for k in range(i - 1, max(i - 4, -1), -1) if not _JUNK_TITLE_RE.search(L[k]) and len(L[k]) <= 120), "")
            title = re.sub(r"\s+", " ", title).strip(" :-")
            nxt = (labels[n + 1] - 1) if n + 1 < len(labels) else end_page   # next block's title line
            block = L[i:max(i + 1, min(nxt, end_page))]
            m = _LABEL_DATE_RE.match(block[0])
            dtxt = (m.group(1) or "").strip(" :") or (block[1] if len(block) > 1 else "")
            dates = _parse_dates(dtxt, today)
            if not title or not dates or (dates[1] or dates[0]) < today.isoformat():
                continue
            loc = None
            for j, l in enumerate(block):
                lm = _LABEL_LOC_RE.match(l)
                if lm:
                    loc = (lm.group(1) or "").strip(" :") or next((x.strip(" :") for x in block[j + 1:j + 3] if not x.startswith("⟦")), None)
                    if loc and loc.startswith(":"):
                        loc = loc.lstrip(": ")
                    break
            links = [_unwrap(h) for l in block for h in re.findall("⟦([^⟧]+)⟧", l)]
            links = [h for h in links if h.startswith("http") and "biasp.org/wp-content" not in h and "youtu" not in h]
            desc = next((l for l in block[1:] if len(l) > 80 and not l.startswith("⟦") and not re.match(r"click here|registration", l, re.I)), None)
            key = (title.lower(), dates[0])
            if key in seen:
                continue
            seen.add(key)
            url = f"{_URL}#{_slug(title)}"
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": dates[0], "end_date": dates[1],
                           "start_time": None, "venue_raw": loc, "category": None,
                           "_register_url": links[0] if links else None, "_desc": re.sub(r"⟦[^⟧]*⟧", "", desc).strip() if desc else None,
                           "is_sold_out": False})
        logger.info(f"BIASP: {len(shells)} upcoming event blocks of {len(labels)}")
        return shells or None

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        title = shell.get("title") or ""
        et = classify_event_type(title, "")
        if et == "workshop" and re.search(r"forum|meeting|conference|congress|anniversary", title, re.I):
            et = "conference"
        out: Dict[str, Any] = {"society": self.SOCIETY, "event_type": et,
                               "start_date": shell.get("start_date"), "end_date": shell.get("end_date")}
        raw = re.sub(r"\s+", " ", (shell.get("venue_raw") or "")).strip(" .,")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts and parts[-1] in _COUNTRIES:
            out["region"] = parts.pop()
        if len(parts) >= 2:
            out["city"] = parts[-1]
            out["venue_name"] = clip_venue(", ".join(parts[:-1]))
        elif len(parts) == 1 and not re.match(r"online|virtual", parts[0], re.I):
            if _VENUE_KW_RE.search(parts[0]):
                out["venue_name"] = clip_venue(parts[0])
            else:
                out["city"] = parts[0]
        if raw and re.match(r"online|virtual", raw, re.I):
            out["event_format"] = "online"
        elif raw:
            out["event_format"] = "in_person"
        if shell.get("_desc"):
            out["description"] = shell["_desc"][:600]
        out["specialty"] = "Neurology"                              # stroke medicine has no taxonomy entry of its own; the site maps Neurology
        if shell.get("_register_url"):
            out["organiser_url"] = shell["_register_url"]
            out["booking_url"] = shell["_register_url"]
        return out
