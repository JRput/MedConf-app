"""PCR (Paris Course on Revascularization / EuroPCR family) courses: pcronline.com/Courses.

pcronline.com is an eZ Publish site, fully server-rendered. `/Courses` shows one block per course:
`<p class="navigation-link">PCR London Valves - 22-24 November 2026</p>` inside `<a class="single-content-item" href=...>`.
Titles carry the dates after the last " - "; courses without dates yet ("PCR Fellows Course | Paris") are skipped, so are
past ones. Two cards redirect to another course (PCR Gulf Valves -> GulfPCR-GIM): dropped as duplicates.

Course pages carry an `Event` JSON-LD block (name, startDate/endDate, location name + city + country). It is only used
for the venue: the visible card dates win when they disagree (Alfieri's Bootcamp JSON-LD is stale). Malformed blocks
are read with regexes, never json.loads.

Fees live on the course's own `/Register` page (same site): `.pricing-item > ul.package` with a category header, the
CURRENT price (`price-current`) for the timeframe flagged `pricing-active`, and the other timeframes as
`price-text`/`price-small` pairs, plus optional "Digital: EUR 500" lines. Exhibitor, industry and emerging-company
categories are not delegate fees and are dropped. Innovators Day prints a second "STAND ALONE" matrix table which is
its own fee (the pricing-items there are the EuroPCR bundle), so that table is used instead.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html

_ROOT = "https://www.pcronline.com"
_LIST_URL = _ROOT + "/Courses"
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# listing cards whose URL redirects to another listed course (checked 2026-10-21: 302 -> /Courses/GulfPCR-GIM)
_ALIASES = {"/Courses/PCR-Gulf-Valves": "/Courses/GulfPCR-GIM"}
_NOT_DELEGATE_RE = re.compile(r"(?i)exhibitor|industry|emerging compan")
_CARD_RE = re.compile(r'(?is)<a href="([^"]+)" class="single-content-item">(.*?)</a>')
_CURRENCY = {"€": "EUR", "$": "USD", "£": "GBP"}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag or ""))).replace("\xa0", " ").strip()


def _mon(s: str) -> Optional[int]:
    return _MONTHS.get((s or "")[:3].lower())


def parse_dates(text: str) -> Optional[Tuple[str, str]]:
    """"23-24 October 2026" / "30 October - 2 November 2026" / "22 October 2026" -> (start, end) ISO (pure)."""
    t = _txt(text).replace("–", "-")
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", t)
    try:
        if m and _mon(m.group(3)):
            mo, y = _mon(m.group(3)), int(m.group(4))
            return date(y, mo, int(m.group(1))).isoformat(), date(y, mo, int(m.group(2))).isoformat()
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s*-\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", t)
        if m and _mon(m.group(2)) and _mon(m.group(4)):
            y2 = int(m.group(5))
            y1 = y2 - 1 if _mon(m.group(2)) > _mon(m.group(4)) else y2
            return date(y1, _mon(m.group(2)), int(m.group(1))).isoformat(), date(y2, _mon(m.group(4)), int(m.group(3))).isoformat()
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", t)
        if m and _mon(m.group(2)):
            d = date(int(m.group(3)), _mon(m.group(2)), int(m.group(1))).isoformat()
            return d, d
    except ValueError:
        return None
    return None


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """/Courses -> one dict per card (title, path, start_date, end_date, blurb); undated cards have no dates (pure)."""
    out: List[Dict[str, Any]] = []
    for href, body in _CARD_RE.findall(html or ""):
        label = re.search(r'(?is)<p class="navigation-link">(.*?)</p>', body)
        if not label:
            continue
        label_t = _txt(label.group(1))
        blurb = re.search(r'(?is)<p class="paragraph">(.*?)</p>', body)
        title, dates = label_t, parse_dates(label_t)
        m = re.match(r"^(.*\S)\s+-\s+(\d.*)$", label_t)
        if m and dates:
            title = m.group(1).strip()
        out.append({"title": title, "path": _html.unescape(href), "start_date": dates[0] if dates else None,
                    "end_date": dates[1] if dates else None, "blurb": _txt(blurb.group(1)) if blurb else None})
    return out


def jsonld_place(html: str) -> Dict[str, Optional[str]]:
    """Venue, city and country from the Event JSON-LD, by regex (the block is sometimes invalid JSON)."""
    m = re.search(r'(?is)<script type="application/ld\+json">(.*?)</script>', html or "")
    blk = m.group(1) if m else ""
    if '"Event"' not in blk:
        return {}
    loc = re.search(r'(?is)"location"\s*:\s*\{.*', blk)
    seg = loc.group(0) if loc else ""
    g = lambda k: (re.search(r'"%s"\s*:\s*"([^"]*)"' % k, seg) or [None, None])[1]
    return {"venue_name": _html.unescape(g("name") or "").strip() or None,
            "city": _html.unescape(g("addressLocality") or "").strip() or None,
            "region": _html.unescape(g("addressCountry") or "").strip() or None}


def _price(text: str) -> Optional[Tuple[float, str]]:
    """"€1,350" / "750 SGD" / "675 €" / "Free" -> (amount, currency) (pure)."""
    t = _txt(text)
    if re.fullmatch(r"(?i)free", t):
        return 0.0, ""
    ttc = re.search(r"(\d[\d\s.,]*\d|\d)\s*([€$£])?\s*TTC", t)       # "3400€ HT - 4148€ TTC": pay the VAT-inclusive figure
    if ttc:
        return float(re.sub(r"[,\s]", "", ttc.group(1))), _CURRENCY.get(ttc.group(2) or "", "")
    m = re.search(r"([€$£]|\b[A-Z]{3}\b)?\s*(\d[\d,. ]*\d|\d)\s*([€$£]|\b[A-Z]{3}\b)?", t)
    if not m:
        return None
    cur = m.group(1) or m.group(3) or ""
    try:
        amount = float(re.sub(r"[,\s]", "", m.group(2)))
    except ValueError:
        return None
    return amount, _CURRENCY.get(cur, cur)


def _period_end(text: str, event_start: Optional[str]) -> Optional[str]:
    """"5 MAY - 8 JUL" -> the end date, in the year that puts it on or before the event start (pure)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s*$", _txt(text).replace("–", "-"))
    if not m or not _mon(m.group(2)) or not event_start:
        return None
    try:
        ev = date.fromisoformat(event_start)
        d = date(ev.year, _mon(m.group(2)), int(m.group(1)))
        if d > ev + timedelta(days=1):
            d = date(ev.year - 1, d.month, d.day)
        return d.isoformat()
    except ValueError:
        return None


def _category(raw: str) -> str:
    c = _txt(raw).strip(" :")
    return c.title().replace("Naps", "NAPs") if c.isupper() else c


def _tier(cat: str, timing: Optional[str], amount: float, cur: str, default_cur: str, deadline: Optional[str] = None) -> Dict[str, Any]:
    early = bool(timing and re.search(r"(?i)early", timing))
    return {"tier_label": " · ".join(x for x in ("Registration", cat, timing and timing.strip().capitalize()) if x)[:120],
            "price_gbp": amount, "currency": cur or default_cur, "is_early_bird": early,
            "early_bird_deadline": deadline if early else None}


def parse_register(html: str, event_start: Optional[str], default_cur: str = "EUR") -> List[Dict[str, Any]]:
    """/Register page -> tiers (pure)."""
    if not html:
        return []
    html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html)
    periods: Dict[str, Optional[str]] = {}
    active = None
    for li in re.findall(r'(?is)<li class="pricing-section([^"]*)">(.*?)</li>', html):
        nm = re.search(r'price-name">(.*?)</span>', li[1], re.S)
        tx = re.search(r'price-text">(.*?)</span>', li[1], re.S)
        if nm:
            key = _txt(nm.group(1)).lower().replace(" ", "")
            periods[key] = _period_end(tx.group(1), event_start) if tx else None
            if "pricing-active" in li[0]:
                active = _txt(nm.group(1))
    for cur_txt in re.findall(r'(?is)price-current">(.*?)</span>', html):
        q = _price(cur_txt)
        if q and q[1]:
            default_cur = q[1]                                   # "Free" rows take the page's currency
            break
    tiers: List[Dict[str, Any]] = []
    stand = re.search(r"(?is)STAND\s*ALONE.*?<table.*?</table>", html)
    if stand:                                                    # matrix: columns "EARLY (13 OCT - 10 FEB)"
        rows = [[_txt(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)] for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", stand.group(0))]
        head = rows[0] if rows else []
        for r in rows[1:]:
            if not r or _NOT_DELEGATE_RE.search(r[0]):
                continue
            for col, cell in zip(head[1:], r[1:]):
                p = _price(cell)
                name = re.match(r"(?i)^\s*([A-Za-z ]+?)\s*(?:\(|$)", col)
                if not p or not name or re.search(r"(?i)on\s?site", name.group(1)):
                    continue
                end = _period_end(col.rstrip(") "), event_start)
                if end and end < date.today().isoformat():
                    continue
                tiers.append(_tier("Innovators Day stand-alone · " + _category(r[0]), name.group(1), p[0], p[1], default_cur, end))
        return tiers
    for item in re.findall(r'(?is)<div class="pricing-item">(.*?)</ul>\s*</div>', html):
        head = re.search(r'(?is)<li class="header">(.*?)</li>', item)
        cur = re.search(r'(?is)price-current">(.*?)</span>', item)
        if not head or not cur or _NOT_DELEGATE_RE.search(_txt(head.group(1))):
            continue
        cat = _category(head.group(1))
        p = _price(cur.group(1))
        if p:
            timing = active
            if re.search(r"(?i)digital", cat):
                timing = None
            tiers.append(_tier(cat, timing, p[0], p[1], default_cur, periods.get((active or "").lower().replace(" ", ""))))
        for name, val in re.findall(r'(?is)price-text">(.*?)</span>\s*<span class="price-small">(.*?)</span>', item):
            q = _price(val)
            nm = _txt(name)
            if q and nm and not re.search(r"(?i)on\s?site", nm):
                tiers.append(_tier(cat, nm, q[0], q[1], default_cur, periods.get(nm.lower().replace(" ", ""))))
        dig = re.search(r"(?i)digital\s*:?\s*([€$£]?\s*\d[\d,.]*\s*(?:[€$£]|[A-Z]{3})?)", _txt(item.split('</li>', 2)[-1]))
        if dig and not re.search(r"(?i)digital", cat):
            q = _price(dig.group(1))
            if q:
                tiers.append(_tier("Digital · " + cat, None, q[0], q[1], default_cur))
    if not tiers:                                                # Alfieri's Bootcamp: "3400€ HT - 4148€ TTC"
        m = re.search(r"(?is)<h\d[^>]*>\s*([^<]{3,60}?)\s*</h\d>\s*<[^>]+>\s*([\d\s.,]+)\s*€\s*HT\s*-\s*([\d\s.,]+)\s*€\s*TTC", html)
        if m:
            p = _price(m.group(3) + "€")
            if p:
                tiers.append(_tier(_category(m.group(1)), None, p[0], "EUR", default_cur))
    seen, out = set(), []
    for t in tiers:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def event_type_for(title: str, start: Optional[str], end: Optional[str]) -> str:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 if start and end else 1
    if days <= 3 and re.search(r"(?i)fellows|boot ?camp|pre-?course|physiology|fundamentals|innovators day|masterclass", title):
        return "workshop"
    return "conference"


class PcronlineExtractor(BaseExtractor):
    SOCIETY = "PCR"
    DEFAULT_SPECIALTY = "Cardiology"
    REQUEST_GAP_S = 1.0

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(_LIST_URL, browser=getattr(self, "browser", None))
        if not html:
            return None
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for c in parse_listing(html):
            path = _ALIASES.get(c["path"], c["path"])
            if path != c["path"]:
                logger.info(f"PCR: dropping {c['title']!r}, redirects to {path}")
                continue
            if not c["start_date"]:
                logger.info(f"PCR: skipping undated card {c['title']!r}")
                continue
            if c["end_date"] < today:
                continue
            url = urljoin(_ROOT, path)
            if url in seen:
                continue
            seen.add(url)
            shells.append({"title": c["title"], "booking_url": url, "source_url": url, "start_date": c["start_date"],
                           "end_date": c["end_date"], "venue_raw": None, "category": None, "blurb": c["blurb"]})
        logger.info(f"PCR: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = fetch_html(shell["booking_url"], browser=getattr(self, "browser", None), loaded_page=page) or ""
        title = shell.get("title") or ""
        start, end = shell.get("start_date"), shell.get("end_date")
        out: Dict[str, Any] = {"society": self.SOCIETY, "start_date": start, "end_date": end,
                               "event_type": event_type_for(title, start, end)}
        if re.fullmatch(r"(?i)europcr", title.strip()):
            out["is_flagship"] = True
        place = jsonld_place(html)
        vn = place.get("venue_name") or ""
        norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
        if vn and (re.search(r"\b20\d\d\b|(?i:all about)", vn) or norm(vn)[:14] == norm(title)[:14]):
            place["venue_name"] = None                               # JSON-LD name is the event title on some pages
        if not place.get("city") and place.get("region") == "Singapore":
            place["city"] = "Singapore"
        for k, v in place.items():
            if v:
                out[k] = v
        if place.get("city") or place.get("venue_name"):
            out["event_format"] = "in_person"
        # description: the listing blurb, else the page strapline (h2.event-title)
        desc = shell.get("blurb")
        if not desc:
            h2 = re.search(r'(?is)<h2 class="heading-two event-title">(.*?)</h2>', html)
            desc = _txt(h2.group(1)) if h2 else None
        if desc:
            out["description"] = desc[:600]
        out["specialty"] = self.DEFAULT_SPECIALTY                  # every PCR course is interventional cardiology
        # fees: the course's /Register page (same site)
        reg = None
        host = urlparse(shell["booking_url"]).path.rstrip("/")
        for m in re.finditer(r'href="(/[^"#?]*?/Register(?:-now)?)"', html, re.I):
            href = _html.unescape(m.group(1))
            if href.lower().startswith(host.lower() + "/"):
                reg = href
                break
        if reg:
            time.sleep(self.REQUEST_GAP_S)
            rhtml = fetch_html(urljoin(_ROOT, reg), browser=getattr(self, "browser", None))
            tiers = parse_register(rhtml or "", start)
            if tiers:
                out["pricing_tiers"] = tiers
        return out
