"""ESHRE (European Society of Human Reproduction and Embryology): Campus workshops + Annual Meeting.

LISTING (`/en/Education/Calendar-Campus-events`, Sitecore, server-rendered, no pagination): one
`<a href="/en/Education/Calendar-Campus-events/<slug>">` per workshop wrapping a `div.grid-item` with the title
(`p.w-title`), a one-sentence blurb, a `fa-map-marker` line ("Florence, Italy") and a `fa-calendar` line
("30-31 October 2026"). The grid-item class says `places-available` or `fully-booked` (=> is_sold_out).

The flagship Annual Meeting is not in that calendar. `/Annual-Meeting` lists each year as "The 43rd Annual Meeting of
ESHRE will be held from 4 to 7 July 2027 in Stockholm, Sweden." with a link to `/en/Annual-Meeting/ESHRE-2027`, whose
page names the venue. Only sections that have not ended are turned into shells.

DETAIL (workshop): header line with dates and place, "ESHRE Campus workshop organised by the Special Interest Group ...",
a course description, the EACCME credit line ("... for a maximum of 8.5 European CME credits"), a `Venue` block (hotel
name, room, street, city) and a `Registration` link to `<event>/Registration` (same site). That page prints a plain table:
Member / Allied professional or student member / Non-member x Early rate (until <date>) / Standard rate. Early columns
whose deadline has passed are dropped. Fees are quoted in euros.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html

_ROOT = "https://www.eshre.eu"
_LIST_URL = _ROOT + "/en/Education/Calendar-Campus-events"
_AM_URL = _ROOT + "/Annual-Meeting"
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_CARD_RE = re.compile(r'(?is)<a href="(/en/Education/Calendar-Campus-events/[^"]+)">\s*<div class="grid-item([^"]*)".*?</a>')


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag or ""))).replace("\xa0", " ").strip()


def _mon(s: str) -> Optional[int]:
    return _MONTHS.get((s or "")[:3].lower())


def parse_dates(text: str) -> Optional[Tuple[str, str]]:
    """"30-31 October 2026" / "28 April - 2 May 2027" / "4 to 7 July 2027" / "29 June to 2 July 2025" -> (start, end) (pure)."""
    t = _txt(text).replace("–", "-")
    try:
        m = re.search(r"(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", t)
        if m and _mon(m.group(3)):
            mo, y = _mon(m.group(3)), int(m.group(4))
            return date(y, mo, int(m.group(1))).isoformat(), date(y, mo, int(m.group(2))).isoformat()
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s*(?:-|to)\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", t)
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


def split_place(raw: str) -> Dict[str, str]:
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    out: Dict[str, str] = {}
    if parts:
        out["city"] = parts[0]
    if len(parts) >= 2:
        out["region"] = parts[-1]
    return out


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Campus calendar -> one dict per card (pure)."""
    out: List[Dict[str, Any]] = []
    for m in _CARD_RE.finditer(html or ""):
        card = m.group(0)
        title = re.search(r'(?is)<p class="w-title">(.*?)</p>', card)
        marker = re.search(r'(?is)fa-map-marker[^>]*></i>(.*?)</p>', card)
        cal = re.search(r'(?is)fa-calendar[^>]*></i>(.*?)</p>', card)
        if not title or not cal:
            continue
        dates = parse_dates(cal.group(1))
        paras = [_txt(p) for p in re.findall(r"(?is)<p>(.*?)</p>", card)]
        blurb = next((p for p in paras if len(p) > 60), None)
        out.append({"title": _txt(title.group(1)), "path": _html.unescape(m.group(1)), "start_date": dates[0] if dates else None,
                    "end_date": dates[1] if dates else None, "place": _txt(marker.group(1)) if marker else "",
                    "blurb": blurb, "sold_out": "fully-booked" in m.group(2)})
    return out


def parse_annual_meetings(html: str) -> List[Dict[str, Any]]:
    """/Annual-Meeting -> [{title, start_date, end_date, place, path}] for every year listed (pure)."""
    out: List[Dict[str, Any]] = []
    text = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>", " ", html or "")
    for h in re.finditer(r"(?is)<h\d[^>]*>\s*(\d{4}) Annual Meeting\s*</h\d>(.*?)(?=<h\d[^>]*>\s*\d{4} Annual Meeting|<h\d[^>]*>\s*Past Annual|$)", text):
        body = _txt(h.group(2))
        dates = parse_dates(body)
        if not dates:
            continue
        place = re.search(r"(?i)\bin\s+([A-Z][A-Za-z .'-]+?),\s*([A-Z][A-Za-z .'-]+?)(?:\s+from\b|\.|\s+Click|$)", body) \
            or re.search(r"(?i)\bin\s+([A-Z][A-Za-z .'-]+?),\s*([A-Z][A-Za-z .'-]+?)\.", body)
        link = re.search(r'href="(/en/Annual-Meeting/[^"]+)"', h.group(2))
        edition = re.search(r"(?i)The\s+(\d+(?:st|nd|rd|th))\s+Annual Meeting", body)
        out.append({"year": int(h.group(1)), "start_date": dates[0], "end_date": dates[1],
                    "city": place.group(1).strip() if place else None, "region": place.group(2).strip() if place else None,
                    "path": _html.unescape(link.group(1)) if link else None, "edition": edition.group(1) if edition else None})
    return out


def _deadline(text: str, event_start: Optional[str]) -> Optional[str]:
    m = re.search(r"(?i)(?:until\s+)?(\d{1,2})\s+([A-Za-z]{3,9})\b", _txt(text))
    if not m or not _mon(m.group(2)) or not event_start:
        return None
    ev = date.fromisoformat(event_start)
    try:
        d = date(ev.year, _mon(m.group(2)), int(m.group(1)))
        if d > ev:
            d = date(ev.year - 1, d.month, d.day)
        return d.isoformat()
    except ValueError:
        return None


def _amount(raw: str) -> Optional[float]:
    """"305" / "1,200" / "312,50" / "312.50" -> float: a last separator followed by 1-2 digits is the decimal point (pure)."""
    raw = (raw or "").strip(".,")
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,](\d{1,2}))?", raw)
    if not m:
        return None
    return float(re.sub(r"[.,]", "", m.group(1)) + ("." + m.group(2) if m.group(2) else ""))


def _category(label: str) -> str:
    c = re.sub(r"(?i)\s+of ESHRE\s*$", "", _txt(label)).strip(" :")
    return c[:1].upper() + c[1:] if c else c


def parse_fees(html: str, event_start: Optional[str]) -> List[Dict[str, Any]]:
    """`<event>/Registration` page -> tiers (pure)."""
    today = date.today().isoformat()
    tiers: List[Dict[str, Any]] = []
    for tbl in re.findall(r"(?is)<table\b.*?</table>", html or ""):
        rows = [[_txt(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)] for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tbl)]
        if len(rows) < 2 or not re.search(r"(?i)rate", " ".join(rows[0])):
            continue
        head = rows[0]
        for r in rows[1:]:
            if len(r) < 2 or not r[0]:
                continue
            for col, cell in zip(head[1:], r[1:]):
                m = re.search(r"(\d[\d,.]*)\s*(?:Euro|EUR|€)|(?:€|EUR)\s*(\d[\d,.]*)", cell, re.I)
                if not m:
                    continue
                amount = _amount(m.group(1) or m.group(2))
                if amount is None:
                    continue
                early = bool(re.search(r"(?i)early", col))
                dl = _deadline(col, event_start) if early else None
                if early and dl and dl < today:
                    continue                                         # early rate already over
                timing = "Early" if early else "Standard"
                tiers.append({"tier_label": " · ".join(("Registration", _category(r[0]), timing))[:120], "price_gbp": amount,
                              "currency": "EUR", "is_early_bird": early, "early_bird_deadline": dl})
    return tiers


_NAV_RE = re.compile(r"(?i)\b(?:home|menu|login|log in|register|read more|cookies?|skip to|share this|privacy|terms|breadcrumb|myeshre)\b")


def clean_description(text: Optional[str]) -> Optional[str]:
    """Cut at 'Read more', reject text that still carries menu/breadcrumb/cookie phrases or is too short (pure)."""
    t = re.split(r"(?i)\bread more\b", text or "")[0].strip()
    return t[:800] if len(t) >= 40 and not _NAV_RE.search(t) else None


def venue_from_page(html: str) -> Optional[str]:
    """Workshop page: `w-title Venue` widget -> `innertextandlinks` <p> first line. Annual Meeting page: `<h4>Venue</h4>` block."""
    body = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>", " ", html or "")
    m = re.search(r'(?is)<p class="w-title"><strong>Venue</strong></p>.*?<div class="innertextandlinks">\s*<p>(.*?)</p>', body) \
        or re.search(r"(?is)<h4>\s*Venue\s*</h4>.*?<p><a[^>]*href=[^>]*>(?!\s*<img)(.*?)</a>", body)
    if not m:
        return None
    first = next((x for x in (_txt(l) for l in re.split(r"<br\s*/?>", m.group(1))) if x), None)
    return first[:150] if first and not re.match(r"(?i)^(room|tbc|tba)\b", first) else None


class EshreExtractor(BaseExtractor):
    SOCIETY = "ESHRE"
    DEFAULT_SPECIALTY = "Obstetrics & Gynaecology"
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
            url = urljoin(_ROOT, c["path"])
            if not c["start_date"] or c["end_date"] < today or url in seen:
                continue
            seen.add(url)
            shells.append({"title": c["title"], "booking_url": url, "source_url": url, "start_date": c["start_date"], "end_date": c["end_date"],
                           "venue_raw": c["place"], "category": "Campus workshop", "blurb": c["blurb"], "is_sold_out": c["sold_out"]})
        time.sleep(self.REQUEST_GAP_S)
        am = fetch_html(_AM_URL, browser=getattr(self, "browser", None))
        for a in parse_annual_meetings(am or ""):
            if a["end_date"] < today or not a["path"]:
                continue
            url = urljoin(_ROOT, a["path"])
            if url in seen:
                continue
            seen.add(url)
            place = ", ".join(x for x in (a["city"], a["region"]) if x)
            title = f"ESHRE {a['year']} Annual Meeting" + (f" ({a['edition']})" if a["edition"] else "")
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": a["start_date"], "end_date": a["end_date"],
                           "venue_raw": place, "category": "Annual Meeting", "blurb": None, "is_sold_out": False, "annual_meeting": True})
        logger.info(f"ESHRE: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = fetch_html(shell["booking_url"], browser=getattr(self, "browser", None), loaded_page=page) or ""
        text = _txt(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer)\b.*?</\1\s*>", " ", html))
        out: Dict[str, Any] = {"society": self.SOCIETY, "specialty": self.DEFAULT_SPECIALTY, "start_date": shell.get("start_date"),
                               "end_date": shell.get("end_date")}
        out.update(split_place(shell.get("venue_raw") or ""))
        if out.get("city"):
            out["event_format"] = "in_person"
        venue = venue_from_page(html)
        if shell.get("annual_meeting"):
            out["event_type"] = "conference"
            out["is_flagship"] = True
        else:
            out["event_type"] = "workshop"
            out["event_format"] = "hybrid" if out.get("city") else None     # "in-person events with live broadcast"
            body_desc = None
            d = re.search(r"(?is)Course description</[^>]+>(.*?)(?:Read more|Organising Secretariat)", html)
            if d:
                paras = [clean_description(_txt(x)) for x in re.findall(r"(?is)<p[^>]*>(.*?)</p>", d.group(1))] or [clean_description(_txt(d.group(1)))]
                body_desc = next((x for x in paras if x), None)
            mm = re.search(r'<meta[^>]+name="description"[^>]*content="([^"]+)"', html)
            out_desc = body_desc or clean_description(_txt(mm.group(1)) if mm else None) or clean_description(shell.get("blurb"))
            if out_desc:
                out["description"] = out_desc
            cme = re.search(r"(?i)maximum of\s*([\d.]+)\s*European CME credits", text)
            if cme:
                out["cpd_points"] = float(cme.group(1))
                out["cpd_accredited"] = True
        if venue:
            out["venue_name"] = venue
        if shell.get("is_sold_out") or re.search(r"(?i)\bRegistration\s+fully booked\b", text):
            out["is_sold_out"] = True
        reg = re.search(r'href="(/en/Education/Calendar-Campus-events/[^"]+/Registration)"', html)
        if reg and not shell.get("annual_meeting"):
            time.sleep(self.REQUEST_GAP_S)
            rhtml = fetch_html(urljoin(_ROOT, _html.unescape(reg.group(1))), browser=getattr(self, "browser", None))
            tiers = parse_fees(rhtml or "", shell.get("start_date"))
            if tiers:
                out["pricing_tiers"] = tiers
        return out
