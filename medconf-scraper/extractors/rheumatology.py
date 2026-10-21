"""BSR (British Society for Rheumatology) conferences, courses and webinars: WordPress-family subclass, DNN site.

`rheumatology.org.uk` runs on DNN (DotNetNuke). Its listing modules are server-rendered: each of
`/events-learning/conferences`, `/courses` and `/webinars` holds `div.article` blocks (title link, teaser, and a footer
"03-04 November 2026 | Conferences"). The "Loading more" button is vestigial: the module's own JSON says
`TotalCount` equals the number of blocks already in the HTML (2 conferences, 5 courses, 3 webinars on 2026-10-21).

Gotchas handled here:
- **Stale listing dates.** The Annual Conference card still says "28-30 April 2026" after the 2027 event was announced;
  the detail page's `Date` line says 2027. A card whose date is past, or that has none (an undated webinar), is
  therefore re-read from its detail page, and dropped only if the detail date is also past or missing.
- **On-demand courses** (footer "On-demand") have no date and are skipped.
- **Webinars without a year** ("30 November 4-5pm") resolve to the next occurrence of that day.

Detail pages share one layout: `Date` / `Venue` / `CPD` labels each followed by a value line, a description, and a
`Pricing` block with a Members tab and a Non-members tab (`div.item` = name, description, `div.price` + "+VAT").
Public webinars say "free to attend" (members-only ones too); that is stored as a Members / Free tier.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from logger import logger

from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, clip_venue, dedupe_consecutive, find_dates, pick_event_dates)
from .http_fetch import fetch_html

_ROOT = "https://www.rheumatology.org.uk"
_SECTIONS = [("conferences", "conference"), ("courses", "course"), ("webinars", "workshop")]
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_UK_CITIES = {
    "London": "England", "Birmingham": "England", "Manchester": "England", "Liverpool": "England", "Leeds": "England",
    "Sheffield": "England", "Bristol": "England", "Newcastle": "England", "Nottingham": "England", "Leicester": "England",
    "Oxford": "England", "Cambridge": "England", "Southampton": "England", "Harrogate": "England", "Northampton": "England",
    "Coventry": "England", "York": "England", "Brighton": "England", "Cardiff": "Wales", "Swansea": "Wales",
    "Edinburgh": "Scotland", "Glasgow": "Scotland", "Aberdeen": "Scotland", "Dundee": "Scotland", "Belfast": "Northern Ireland",
}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_bsr_date(text: str, today: Optional[date] = None) -> Optional[Tuple[str, str]]:
    """'03-04 November 2026' / '22 October 2026, 12:30 - 13:30' / '30 November 4-5pm' (no year) -> (start, end)."""
    today = today or date.today()
    text = re.sub(r"\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}", " ", text or "")        # drop a time range
    d = pick_event_dates(text, today)
    if d and re.search(r"\b20\d\d\b", text):
        return d
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–]\s*(\d{1,2})(?:st|nd|rd|th)?)?\s+([A-Za-z]{3,9})\b", text)
    if not m or m.group(3)[:3].lower() not in _MON:
        return d
    mon = _MON[m.group(3)[:3].lower()]
    for y in (today.year, today.year + 1):                  # next occurrence of that day
        s = _iso(y, mon, int(m.group(1)))
        if s and s >= (today - timedelta(days=1)).isoformat():
            e = _iso(y, mon, int(m.group(2))) if m.group(2) else s
            return s, e or s
    return None


def _start_time(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text or "")
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"\b(\d{1,2})\s*[-–]\s*\d{1,2}\s*([ap]m)\b", text or "", re.I)      # "4-5pm" -> starts at 4pm
    if m:
        return f"{int(m.group(1)) % 12 + (12 if m.group(2).lower() == 'pm' else 0):02d}:00"
    return None


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Listing module HTML -> one dict per `div.article` (pure)."""
    out: List[Dict[str, Any]] = []
    for blk in re.findall(r'(?is)<div class="article row">.*?(?=<div class="article row">|<div class="listing-pagination)', html or ""):
        t = re.search(r'(?is)<h2 class="article-title">(.*?)</h2>', blk)
        a = re.search(r'(?is)<a[^>]*href="((?:https?://[^"/]*rheumatology\.org\.uk)?/events-learning/[^"#?]+)"', blk)
        foot = re.search(r'(?is)<span class="article-footer">(.*?)</span>', blk)
        if not (t and a):
            continue
        ft = _txt(foot.group(1)) if foot else ""
        out.append({"title": _txt(t.group(1)), "url": _ROOT + re.sub(r"^https?://[^/]*", "", _html.unescape(a.group(1))).lower(),
                    "footer": ft.split("|")[0].strip(), "on_demand": bool(re.search(r"(?i)on[- ]demand", ft))})
    return out


def tab_tiers(html: str) -> List[Dict[str, Any]]:
    """`Pricing` module: membersTab / nonMembersTab `div.item`s -> tiers (pure)."""
    tiers: List[Dict[str, Any]] = []
    for tab_id, label in (("membersTab", "Members"), ("nonMembersTab", "Non-members")):
        m = re.search(rf'(?is)id="{tab_id}"[^>]*>(.*?)(?=id="(?:members|nonMembers)Tab"|<div class="cta|</div>\s*</div>\s*</div>\s*</div>)', html or "")
        if not m:
            continue
        for item in re.findall(r'(?is)<div class="item">.*?</div>\s*</div>\s*(?=<div class="item">|$|</div>)', m.group(1)):
            name = re.search(r'(?is)class="item-name">(.*?)</h4>', item)
            desc = re.search(r'(?is)class="item-description">(.*?)</h4>', item)
            price = re.search(r'(?is)class="price">(.*?)</div>', item)
            if not (name and price):
                continue
            p = _txt(price.group(1))
            pm = re.search(r"£\s?(\d[\d,]*(?:\.\d{2})?)", p)
            amount = float(pm.group(1).replace(",", "")) if pm else (0.0 if re.search(r"(?i)\bfree\b", p) else None)
            if amount is None:
                continue
            nm = _txt(name.group(1))
            ds = re.sub(r"\s+", " ", _txt(desc.group(1))) if desc else ""
            ds = ds if 0 < len(ds) <= 80 else ""
            vat = bool(re.search(r"(?i)\+\s*VAT", _txt(item)))
            tiers.append({"tier_label": " · ".join(x for x in (label, nm, ds, "ex VAT" if vat and amount else None) if x)[:120],
                          "price_gbp": amount, "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
    seen, out = set(), []
    for t in tiers:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


class RheumatologyExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/events-learning/conferences"
    SOCIETY = "BSR"
    DEFAULT_SPECIALTY = "Rheumatology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    @staticmethod
    def _labelled(lines: List[str], label: str) -> Optional[str]:
        for i, ln in enumerate(lines):
            if ln.lower() == label.lower() and i + 1 < len(lines):
                return lines[i + 1]
        return None

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        iso_today = today.isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        got = False
        for n, (section, etype) in enumerate(_SECTIONS):
            html = self._fetch(f"{_ROOT}/events-learning/{section}") if n == 0 else fetch_html(f"{_ROOT}/events-learning/{section}", browser=getattr(self, "browser", None))
            if n == 0 and not html:
                return None
            if not html:
                continue
            got = True
            for c in parse_listing(html):
                if c["url"] in seen or c["on_demand"] or re.search(r"(?i)cancel", c["title"]):
                    continue
                seen.add(c["url"])
                d = parse_bsr_date(c["footer"], today) if c["footer"] else None
                if not d or d[1] < iso_today:                    # undated or stale card: the detail page is the authority
                    time.sleep(self.REQUEST_GAP_S)
                    page = fetch_html(c["url"], browser=getattr(self, "browser", None))
                    lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1\s*>", " ", page or "")))
                    dl = self._labelled(lines, "Date")
                    d2 = parse_bsr_date(dl, today) if dl else None
                    if not d2 or d2[1] < iso_today:
                        continue
                    d = d2
                    st = _start_time(dl)
                else:
                    st = None
                shells.append({"title": c["title"], "booking_url": c["url"], "source_url": c["url"], "start_date": d[0], "end_date": d[1],
                               "start_time": st, "venue_raw": None, "category": etype, "bsr_type": etype})
            time.sleep(self.REQUEST_GAP_S)
        if not got:
            return None
        logger.info(f"BSR: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    @staticmethod
    def _venue(raw: Optional[str]) -> Dict[str, Any]:
        if not raw:
            return {}
        if re.match(r"(?i)^(online|virtual|webinar)\b", raw) and not re.search(r"(?i)\bin[- ]person\b", raw):
            return {"event_format": "online"}
        hybrid = bool(re.search(r"(?i)\band online\b|\bhybrid\b", raw))
        base = re.sub(r"(?i)\s*(?:,|and)?\s*(?:and\s+)?online$", "", raw).strip(" ,")
        city = next((c for c in _UK_CITIES if re.search(rf"\b{c}\b", base)), None)
        out: Dict[str, Any] = {"venue_name": clip_venue(base), "event_format": "hybrid" if hybrid else "in_person"}
        if city:
            out["city"] = city
            out["region"] = _UK_CITIES[city]
        return out

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer|header)\b.*?</\1\s*>", " ", html)))
        dl = self._labelled(lines, "Date")
        d = parse_bsr_date(dl) if dl else None
        out["start_date"], out["end_date"] = (d if d else (shell["start_date"], shell.get("end_date") or shell["start_date"]))
        st = _start_time(dl or "") or shell.get("start_time")
        if st:
            out["start_time"] = st
        h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
        if h1 and _txt(h1.group(1)):
            out["conference_name"] = _txt(h1.group(1))
        out["event_type"] = shell.get("bsr_type") or out.get("event_type")
        for k in ("venue_name", "city", "region", "event_format"):
            out.pop(k, None)
        venue = self._labelled(lines, "Venue")
        out.update(self._venue(venue))
        if "event_format" not in out and out["event_type"] == "workshop":
            out["event_format"] = "online"                      # webinars have no Venue line
        cpd = self._labelled(lines, "CPD")
        if cpd:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:credits?|hours?)", cpd, re.I)
            if m:
                out["cpd_points"] = float(m.group(1))
                out["cpd_accredited"] = True
        tiers = tab_tiers(html)
        if not tiers and re.search(r"(?i)free to attend|free webinar", " ".join(lines)):
            members_only = bool(re.search(r"(?i)exclusive to (?:BSR )?members|BSR members only", " ".join(lines)))
            tiers = [{"tier_label": ("Members" if members_only else "Standard") + " · Free", "price_gbp": 0.0, "currency": "GBP",
                      "is_early_bird": False, "early_bird_deadline": None}]
        if tiers:
            out["pricing_tiers"] = tiers
        else:
            out.pop("pricing_tiers", None)
        return out
