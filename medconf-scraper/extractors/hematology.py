"""ASH (American Society of Hematology) meetings: Sitecore site, server-rendered, bespoke extractor.

`hematology.org/meetings` is one page with five sections: the ASH Annual Meeting and four "Highlights of ASH" regional
programmes (North America in four cities, Asia-Pacific, Mediterranean/Middle East/North Africa, Latin America). Each section
states the NEXT edition in a "taking place <Month d-d, yyyy>, in <City>, <Country>" sentence (North America lists
"<Month d-d> in <City>, <ST>" lines). The programme pages still carry last edition's text next to the new one (Kuala
Lumpur / Istanbul), so dates, city and venue are read from the listing and from the line AFTER the current edition's date,
never from the first date on a programme page.

Fees are public HTML grids on the programme's registration page (`/registration-information` for the Annual Meeting):
header "Registration Category | Advance Registration (Ends <date>) | Late/Onsite (Begins <date>)", or option columns
(In-Person, Extended Flexibility, Best Value) under an "Advance registration - Ends <date>" heading. USD. A fee page is only
used when it names the edition's year (a stale grid must not leak into the new edition's row). North America's four
cities share one fee page, fetched once.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import find_dates

_ROOT = "https://www.hematology.org"
_LISTING = _ROOT + "/meetings"
_SOCIETY = "American Society of Hematology (ASH)"
_REQUEST_GAP_S = 1.0
_MAX_FUTURE_DAYS = 550                       # 18 months: farther out is a placeholder, not a listing
_RANGE = r"[A-Z][a-z]+ \d{1,2}\s*[\u2013\u2014-]\s*\d{1,2}"

# key, exact heading line on /meetings, programme path, short title
_PROGRAMMES = [
    ("annual", "ASH Annual Meeting", "/meetings/annual-meeting"),
    ("na", "Highlights of ASH in North America", "/meetings/highlights-of-ash-in-north-america"),
    ("apac", "Highlights of ASH in Asia-Pacific", "/meetings/highlights-of-ash-in-asia-pacific"),
    ("memena", "Highlights of ASH in the Mediterranean, Middle East, and North Africa",
     "/meetings/highlights-of-ash-in-the-mediterranean-middle-east-and-north-africa"),
    ("latam", "Highlights of ASH in Latin America", "/meetings/highlights-of-ash-in-latin-america"),
]
_US = "United States"
_COUNTRY_FIX = {"USA": _US, "US": _US, "United States of America": _US, "Turkiye": "Turkey"}

# ---- public fee grids (header row "Registration Category/Type | <column> | <column>") -> tiers -----------------------------
_GRID_LEAD_RE = re.compile(r"(?i)registration\s+(?:category|type)")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DEADLINE_RE = re.compile(
    r"(?i)(?:ends?|on or before|before|register by|until|through)\s*:?\s*"
    r"(?:(\d{1,2})/(\d{1,2})/(\d{2,4})|([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?)")


def _cell_txt(frag: str) -> str:
    frag = re.sub(r"(?is)<sup\b.*?</sup\s*>", " ", frag)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", frag)).replace("\xa0", " ").replace("﻿", "")
    return re.sub(r"\s+", " ", t).strip()


def _grid_price(s: str) -> Optional[float]:
    s = s.strip()
    if re.match(r"(?i)^(?:no charge|complimentary|free)\b", s):
        return 0.0
    m = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", s)
    return float(m.group(1).replace(",", "")) if m else None


def _deadline_iso(text: str, ref_year: int) -> Optional[str]:
    """First 'ends/by/before <date>' in text -> ISO. A date without a year takes ref_year."""
    m = _DEADLINE_RE.search(text or "")
    if not m:
        return None
    try:
        if m.group(1):
            y = int(m.group(3))
            return date(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2))).isoformat()
        mon = _MONTHS.get(m.group(4).lower())
        return date(int(m.group(6)) if m.group(6) else ref_year, mon, int(m.group(5))).isoformat() if mon else None
    except ValueError:
        return None


def grid_tiers(html: str, *, currency: str, ref_year: int, section_for=None, page_text: str = "") -> List[Dict[str, Any]]:
    """Every public fee grid on the page. Column headers become the timeframe/option; deadlines come from the header
    ('Ends January 4, 2027', 'Received on or before 5/31/2026'), else from the 'early bird ... until <date>' sentence."""
    out: List[Dict[str, Any]] = []
    for tm in re.finditer(r"(?is)<table\b[^>]*>(.*?)</table\s*>", html or ""):
        rows = re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr\s*>", tm.group(1))
        cells = [re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", r) for r in rows]
        hi = next((k for k, r in enumerate(cells[:3]) if r and _GRID_LEAD_RE.search(_cell_txt(r[0]))), None)
        if hi is None:                                          # the header row may sit under a one-line banner ("2026 RATES")
            continue
        cells = cells[hi:]
        if len(cells) < 2:
            continue
        ctx = _cell_txt(html[max(0, tm.start() - 900):tm.start()])[-600:]
        section = section_for(ctx) if section_for else "Registration"
        heads = [_cell_txt(c) for c in cells[0]]
        cols: Dict[int, Dict[str, Any]] = {}
        for i, h in enumerate(heads[1:], 1):
            name = re.sub(r"\s*\(.*$", "", h)
            name = re.sub(r"(?i)\s+registration$", "", name.strip())
            name = re.split(r"(?i)\breceived\b|\bbeginning\b|\bbegins\b|\bends?\b|:", name)[0].strip(" :-*")
            if re.fullmatch(r"(?i)(?:registration )?(?:rate|fee|price)", name):
                name = ""
            early = bool(re.search(r"(?i)early|advance|register by", h))
            dl = _deadline_iso(h, ref_year)
            rng = re.search(r"(?i)\(\s*[A-Za-z]{3,9}\.?\s+\d{1,2},?\s*(?:\d{4})?\s*[-\u2013]\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s*(\d{4})", h)
            if early and not dl and rng and rng.group(1).lower() in _MONTHS:      # "(October 1, 2026 - January 29, 2027)": the window's end
                try:
                    dl = date(int(rng.group(3)), _MONTHS[rng.group(1).lower()], int(rng.group(2))).isoformat()
                except ValueError:
                    dl = None
            nr = re.search(r"(?i)between\s+\d{1,2}/\d{1,2}/\d{2,4}\s*[-\u2013]\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", h)
            if early and not dl and nr:                                          # "Received between 6/1/2026- 9/30/26": the window's end
                try:
                    yy = int(nr.group(3))
                    dl = date(yy + 2000 if yy < 100 else yy, int(nr.group(1)), int(nr.group(2))).isoformat()
                except ValueError:
                    dl = None
            if early and not dl and page_text:
                m = re.search(r"(?i)(?:early[- ]bird|advance)[^.]{0,90}?(?:until|ends?|before)\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", page_text)
                if m and m.group(1).lower() in _MONTHS:
                    try:
                        dl = date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
                    except ValueError:
                        dl = None
            cols[i] = {"name": name.title() if name.isupper() else name, "early": early, "deadline": dl if early else None}
        if cols and not any(re.search(r"(?i)advance|early|late|regular|standard|on-?site|register", c["name"]) for c in cols.values()):
            tm2 = re.search(r"(?i)\b(advance|early[- ]bird|late|on-?site)\b[^.]{0,25}registration", ctx[-450:])
            if tm2:                                                 # timeframe stated once above the grid
                adv = bool(re.match(r"(?i)advance|early", tm2.group(1)))
                dl = _deadline_iso(ctx[-450:], ref_year) if adv else None
                for c in cols.values():
                    c.update(tf="Advance" if adv else "Late/On-site", early=adv, deadline=dl)
        for row in cells[1:]:
            if len(row) < 2:
                continue
            strong = re.search(r"(?is)<strong\b[^>]*>(.*?)</strong\s*>", row[0])
            cat = _cell_txt(strong.group(1) if strong else row[0]).strip(" *†‡§:")
            if not cat:
                continue
            for i, col in cols.items():
                p = _grid_price(_cell_txt(row[i])) if i < len(row) else None
                if p is None:
                    continue
                label = " · ".join(x for x in (section, cat[:70], col["name"][:40], col.get("tf")) if x)[:120]
                out.append({"tier_label": label, "price_gbp": p, "currency": currency, "is_early_bird": col["early"],
                            "early_bird_deadline": col["deadline"]})
    seen, uniq = set(), []
    for t in out:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """/meetings HTML -> one dict per upcoming edition (pure): key, path, title, start, end, city, region, format."""
    body = re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer)\b.*?</\1\s*>", " ", html or "")
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    lines = html_to_lines(body)
    idx = {}
    for key, heading, _path in _PROGRAMMES:
        hits = [i for i, l in enumerate(lines) if l == heading]
        if hits:
            idx[key] = hits[-1]                       # the nav list repeats the titles; the section heading is the last hit
    order = sorted(idx.items(), key=lambda kv: kv[1])
    out: List[Dict[str, Any]] = []
    for n, (key, i) in enumerate(order):
        j = order[n + 1][1] if n + 1 < len(order) else len(lines)
        seg = [l for l in lines[i + 1:j]]
        for k, l in enumerate(seg):
            if re.match(r"(?i)^continuing medical education$", l):
                seg = seg[:k]
                break
        text = " ".join(seg)
        path = next(p for kk, _h, p in _PROGRAMMES if kk == key)
        if key == "na":
            year = (re.search(r"\b(20\d\d)\b", text) or [None, None])[1]
            for l in seg:
                m = re.match(rf"^({_RANGE})\s+in\s+([A-Z][\w .'-]+?),\s*([A-Z][A-Za-z.]{{1,3}})\.?$", l)
                if m and year:
                    ds = find_dates(f"{m.group(1)}, {year}")
                    if ds:
                        city = "Washington, DC" if m.group(3).replace(".", "") == "DC" else m.group(2).strip()
                        out.append({"key": key, "path": path, "start": ds[0]["start"], "end": ds[0]["end"], "city": city,
                                    "region": _US, "format": "in_person"})
            continue
        m = re.search(rf"taking place\s+(?:in\s+|on\s+)?({_RANGE},\s*\d{{4}}),?\s+in\s+([A-Z][\w .'\u00c0-\u017f-]+?),\s*([A-Z][\w .'\u00c0-\u017f-]+?)(?:,|[.!]| and online|\s*$)", text)
        if not m:
            continue
        ds = find_dates(m.group(1))
        if not ds:
            continue
        country = m.group(3).strip()
        if key == "annual":
            country = _US                              # "New Orleans, Louisiana": the second part is a state
        title = None
        if key == "annual":
            t = re.search(r"(\d+(?:st|nd|rd|th) ASH Annual Meeting and Exposition)", text)
            title = t.group(1) if t else None
        out.append({"key": key, "path": path, "start": ds[0]["start"], "end": ds[0]["end"], "city": m.group(2).strip(),
                    "region": _COUNTRY_FIX.get(country, country), "format": "hybrid" if re.search(r"(?i)\band online\b", text[:600]) else "in_person",
                    "title": title})
    return out


def _month_day_re(start: str, end: str) -> "re.Pattern[str]":
    """Regex for the edition's date as the site writes it ("February 12-13, 2027", "December 12-15, 2026")."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    mon = s.strftime("%B")
    rng = f"{s.day}" if s == e else rf"{s.day}\s*[–—-]\s*{e.day}"
    return re.compile(rf"{mon}\.?\s+{rng},?\s*{s.year}", re.I)


class HematologyExtractor(BaseExtractor):
    """ASH Annual Meeting + Highlights of ASH regional programmes (hematology.org/meetings)."""

    DEFAULT_SPECIALTY = "Haematology"

    def __init__(self, source: Dict[str, Any]):
        super().__init__(source)
        self._fee_cache: Dict[str, Optional[str]] = {}

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = None
        for attempt in range(3):
            html = fetch_html(_LISTING, browser=getattr(self, "browser", None))
            if html and len(html) > 2000:
                break
            logger.warning(f"ASH listing fetch attempt {attempt + 1}/3 failed")
            time.sleep(2 * (attempt + 1))
        if not html:
            return None
        today = date.today()
        shells: List[Dict[str, Any]] = []
        for r in parse_listing(html):
            start = date.fromisoformat(r["start"])
            if date.fromisoformat(r["end"]) < today or (start - today).days > _MAX_FUTURE_DAYS:
                continue
            heading = next(h for k, h, _p in _PROGRAMMES if k == r["key"])
            if r["key"] == "annual":
                title = r.get("title") or "ASH Annual Meeting and Exposition"
                url = _ROOT + r["path"]
            elif r["key"] == "na":
                title = f"{heading} {start.year} ({r['city']})"
                url = f"{_ROOT}{r['path']}#{re.sub(r'[^a-z]+', '-', r['city'].lower()).strip('-')}-{r['start']}"
            else:
                title = f"{heading} {start.year}"
                url = _ROOT + r["path"]
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": r["start"], "end_date": r["end"],
                           "start_time": None, "venue_raw": None, "category": None, "_key": r["key"], "_path": r["path"],
                           "_city": r["city"], "_region": r["region"], "_format": r["format"]})
        logger.info(f"ASH: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def _fee_page(self, key: str, path: str, shell: Dict[str, Any]) -> Optional[str]:
        sub = "/registration-information" if key == "annual" else "/registration"
        url = _ROOT + path + sub
        if url not in self._fee_cache:
            time.sleep(_REQUEST_GAP_S)
            self._fee_cache[url] = fetch_html(url, browser=getattr(self, "browser", None))
        return self._fee_cache[url]

    @staticmethod
    def _venue(lines: List[str], start: str, end: str) -> Optional[str]:
        """Venue = the line right after THIS edition's date line ("Centara Grand at CentralWorld | Bangkok, Thailand")."""
        rx = _month_day_re(start, end)
        for i, l in enumerate(lines):
            if rx.search(l) and len(l) < 80:
                for nxt in lines[i + 1:i + 3]:
                    cand = re.sub(r"(?i)^venue\s*:\s*", "", nxt).split("|")[0].strip(" ,")
                    if cand and len(cand) <= 70 and not re.search(r"(?i)regist|opens|join|save the date|view|sign up|[.!?]$", cand):
                        return cand
                break
        return None

    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        key, path = shell.get("_key"), shell.get("_path")
        start, end = shell["start_date"], shell.get("end_date") or shell["start_date"]
        out: Dict[str, Any] = {"society": _SOCIETY, "event_type": "conference", "specialty": self.DEFAULT_SPECIALTY,
                               "start_date": start, "end_date": end, "city": shell.get("_city"), "region": shell.get("_region"),
                               "event_format": shell.get("_format")}
        body = re.sub(r"(?s)<!--.*?-->", " ", re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer)\b.*?</\1\s*>", " ", html))
        lines = html_to_lines(body)
        text = " ".join(lines)
        # ---- venue
        if key == "annual":
            m = re.search(r"(?i)held in person at the (.{5,80}?) in [A-Z][\w .]+, [A-Z][\w .]+, and virtually", text)
            if m:
                out["venue_name"] = m.group(1).strip()
        elif key != "na":
            v = self._venue(lines, start, end)
            if v:
                out["venue_name"] = v
        # ---- description: meta description when it says something, else the page's intro sentence
        md = re.search(r"""(?i)<meta\b[^>]*name=["']description["'][^>]*content=["']([^"']*)""", html)
        desc = _html.unescape(md.group(1)).strip() if md else ""
        if len(desc) < 60:
            desc = next((l for l in lines if re.match(r"^Join global hematology leaders", l)), "")
        if desc:
            out["description"] = desc[:600]
        if re.search(r"(?i)\bCME\b", text):
            out["cpd_accredited"] = True
        # ---- Annual Meeting: the abstracts page states the late-breaking deadline in prose (the regular call has closed)
        if key == "annual":
            time.sleep(_REQUEST_GAP_S)
            ab = fetch_html(_ROOT + path + "/abstracts", browser=getattr(self, "browser", None))
            am = re.search(r"(?i)deadline for (late-breaking abstract submission) is ([A-Za-z]{3,9}\.? \d{1,2}, \d{4})", _txt(ab or ""))
            if am:
                ds = find_dates(am.group(2))
                if ds and date.today().isoformat() <= ds[0]["start"] <= start:
                    out["abstract_deadline"] = ds[0]["start"]
                    out["abstract_deadline_note"] = "Late-breaking abstract submission"
        # ---- fees: the programme's registration page, only when it names this edition's year
        fee_html = self._fee_page(key, path, shell) if key and path else None
        if fee_html and str(date.fromisoformat(start).year) in _txt(fee_html):
            plain = _txt(re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", fee_html))
            tiers = grid_tiers(fee_html, currency="USD", ref_year=date.fromisoformat(start).year, page_text=plain)
            stale = [t for t in tiers if t.get("early_bird_deadline") and t["early_bird_deadline"] < f"{date.fromisoformat(start).year - 1}-01-01"]
            tiers = [t for t in tiers if t not in stale]
            if tiers:
                out["pricing_tiers"] = tiers
        return out
