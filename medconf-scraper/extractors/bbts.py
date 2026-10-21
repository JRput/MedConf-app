"""
British Blood Transfusion Society (BBTS) — events extractor.

Platform: bespoke Svelte-SSR CMS by "Duo", server-rendered (the HTML contains
the full list; no JS needed). /events/ is a news-style FEED: events, blog posts,
council profiles and certificate pages are mixed together, newest-dated first.
Only items under `/events/bbts_events/…` are events; every other href is
skipped. The `<small>` date on each feed item is the event's first day (checked
against the bodies of Scotblood 2026, the RCPath & SHOT symposium and LMCE
2026). The feed has no pagination, but a "Monthly Archives" sidebar links
`?month=YYYY-MM` pages; current and future months are fetched too.

Event pages are tiny free-text pages ("Virtual two half day event on 25th and
26th Nov 2026", "Dates: October 21 (Wed) – 23 (Fri), 2026 / Venue: Grand
Walkerhill Seoul, Korea"). Fees are not published on bbts.org.uk: a REGISTER
HERE link leads to the organiser (one hop is followed and read for fee tables).
The BBTS Annual Conference has its own page (/whoweare/whatwedo/annualconference/)
which is added when its text announces a future edition.
"""

from __future__ import annotations

import re
import json
import html as html_lib
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from logger import logger

BASE_URL = "https://www.bbts.org.uk"
LISTING_URL = "https://www.bbts.org.uk/events/"
MONTH_URL = "https://www.bbts.org.uk/events/?month={ym}"
CONFERENCE_PAGE = "https://www.bbts.org.uk/whoweare/whatwedo/annualconference/"
DEFAULT_SPECIALTY = "Transfusion Medicine"

# ---------------------------------------------------------------------------
# Shared helpers (kept inline so this extractor stays one self-contained file,
# same style as the sibling extractors).
# ---------------------------------------------------------------------------
import time
from urllib.parse import urlparse
from safe_fetch import fetch_validated


def host_is(url: str, domain: str) -> bool:
    """Hostname equality or subdomain match (never a substring test)."""
    h = (urlparse(url or "").hostname or "").lower()
    return h == domain or h.endswith("." + domain)


def ext_get(url: str) -> Optional[str]:
    """Fetch a page on ANOTHER host: SSRF-validated, size/time capped, no browser fallback."""
    try:
        verdict, final, body, enc, status = fetch_validated(url, deadline=time.monotonic() + 30, max_bytes=2_000_000)
    except Exception as e:  # pragma: no cover
        logger.warning(f"external hop failed for {url}: {e}")
        return None
    if verdict != "ok" or body is None:
        logger.warning(f"external hop {url} not fetched (verdict={verdict}, status={status})")
        return None
    return body.decode(enc or "utf-8", errors="replace")


_SOCIAL_HOSTS = ("zoom.us", "surveymonkey.com", "linkedin.com", "twitter.com", "x.com", "instagram.com",
                 "facebook.com", "youtube.com", "bsky.app", "google.com", "microsoft.com")

_MON_PAT = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
            r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

_D = r"(?<!\d)(\d{1,2})(?!\d)"
_RANGE_RE = re.compile(
    rf"{_D}\s*({_MON_PAT})?\.?\s*(\d{{4}})?\s*(?:-|to|until|and|&)\s*"
    rf"{_D}\s*(?:of\s+)?({_MON_PAT})\.?\s*(\d{{4}})?", re.I)
_SINGLE_RE = re.compile(rf"{_D}\s*(?:of\s+)?({_MON_PAT})\.?\s*(\d{{4}})?", re.I)
_MF_RANGE_RE = re.compile(
    rf"({_MON_PAT})\.?\s*{_D}\s*(?:-|to|and)\s*{_D}\s*,?\s*(\d{{4}})?", re.I)
_MF_SINGLE_RE = re.compile(rf"({_MON_PAT})\.?\s*{_D}\s*,?\s*(\d{{4}})?", re.I)

_UK_REGIONS = {
    "london": ("London", "London"),
    "manchester": ("Manchester", "North West England"),
    "liverpool": ("Liverpool", "North West England"),
    "leeds": ("Leeds", "Yorkshire and the Humber"),
    "sheffield": ("Sheffield", "Yorkshire and the Humber"),
    "york": ("York", "Yorkshire and the Humber"),
    "hull": ("Hull", "Yorkshire and the Humber"),
    "newcastle": ("Newcastle upon Tyne", "North East England"),
    "gateshead": ("Gateshead", "North East England"),
    "durham": ("Durham", "North East England"),
    "birmingham": ("Birmingham", "West Midlands"),
    "wolverhampton": ("Wolverhampton", "West Midlands"),
    "coventry": ("Coventry", "West Midlands"),
    "stoke": ("Stoke-on-Trent", "West Midlands"),
    "bristol": ("Bristol", "South West England"),
    "bath": ("Bath", "South West England"),
    "exeter": ("Exeter", "South West England"),
    "plymouth": ("Plymouth", "South West England"),
    "cardiff": ("Cardiff", "Wales"),
    "swansea": ("Swansea", "Wales"),
    "newport": ("Newport", "Wales"),
    "edinburgh": ("Edinburgh", "Scotland"),
    "glasgow": ("Glasgow", "Scotland"),
    "aberdeen": ("Aberdeen", "Scotland"),
    "dundee": ("Dundee", "Scotland"),
    "stirling": ("Stirling", "Scotland"),
    "st andrews": ("St Andrews", "Scotland"),
    "belfast": ("Belfast", "Northern Ireland"),
    "cambridge": ("Cambridge", "East of England"),
    "norwich": ("Norwich", "East of England"),
    "ipswich": ("Ipswich", "East of England"),
    "oxford": ("Oxford", "South East England"),
    "brighton": ("Brighton", "South East England"),
    "southampton": ("Southampton", "South East England"),
    "portsmouth": ("Portsmouth", "South East England"),
    "reading": ("Reading", "South East England"),
    "guildford": ("Guildford", "South East England"),
    "leicester": ("Leicester", "East Midlands"),
    "nottingham": ("Nottingham", "East Midlands"),
    "derby": ("Derby", "East Midlands"),
    "lincoln": ("Lincoln", "East Midlands"),
    "northampton": ("Northampton", "East Midlands"),
    "chelmsford": ("Chelmsford", "East of England"),
    "harrogate": ("Harrogate", "Yorkshire and the Humber"),
    "telford": ("Telford", "West Midlands"),
    "warwick": ("Warwick", "West Midlands"),
    "chester": ("Chester", "North West England"),
    "preston": ("Preston", "North West England"),
    "salford": ("Salford", "North West England"),
    "milton keynes": ("Milton Keynes", "South East England"),
    "bournemouth": ("Bournemouth", "South West England"),
    "poole": ("Poole", "South West England"),
    "swindon": ("Swindon", "South West England"),
    "gloucester": ("Gloucester", "South West England"),
    "cheltenham": ("Cheltenham", "South West England"),
    "truro": ("Truro", "South West England"),
    "worcester": ("Worcester", "West Midlands"),
    "shrewsbury": ("Shrewsbury", "West Midlands"),
    "carlisle": ("Carlisle", "North West England"),
    "lancaster": ("Lancaster", "North West England"),
    "blackpool": ("Blackpool", "North West England"),
    "bolton": ("Bolton", "North West England"),
    "wigan": ("Wigan", "North West England"),
    "doncaster": ("Doncaster", "Yorkshire and the Humber"),
    "bradford": ("Bradford", "Yorkshire and the Humber"),
    "huddersfield": ("Huddersfield", "Yorkshire and the Humber"),
    "middlesbrough": ("Middlesbrough", "North East England"),
    "sunderland": ("Sunderland", "North East England"),
    "peterborough": ("Peterborough", "East of England"),
    "colchester": ("Colchester", "East of England"),
    "canterbury": ("Canterbury", "South East England"),
    "maidstone": ("Maidstone", "South East England"),
    "winchester": ("Winchester", "South East England"),
    "basingstoke": ("Basingstoke", "South East England"),
    "dartford": ("Dartford", "South East England"),
    "woking": ("Woking", "South East England"),
    "inverness": ("Inverness", "Scotland"),
    "perth": ("Perth", "Scotland"),
    "wrexham": ("Wrexham", "Wales"),
    "londonderry": ("Londonderry", "Northern Ireland"),
}
_FOREIGN_CITIES = [
    "dublin", "paris", "munich", "zurich", "seoul", "kuala lumpur", "leipzig", "berlin",
    "vienna", "barcelona", "amsterdam", "lisbon", "rome", "madrid", "milan", "brussels",
    "copenhagen", "stockholm", "geneva", "new york", "boston", "chicago", "washington",
    "singapore", "dubai", "hong kong", "tokyo", "sydney", "melbourne", "toronto",
    "san francisco", "las vegas", "orlando", "athens", "prague", "budapest", "warsaw",
    "oslo", "helsinki", "lyon", "nice", "marseille", "cologne", "hamburg", "frankfurt",
    "turin", "istanbul", "cairo", "mumbai", "delhi", "beijing", "shanghai", "bangkok", "doha",
]
_FOREIGN_COUNTRIES = [
    "italy", "france", "germany", "spain", "ireland", "netherlands", "switzerland", "austria",
    "belgium", "portugal", "sweden", "norway", "denmark", "finland", "greece", "poland", "turkey",
    "usa", "united states", "canada", "australia", "china", "japan", "korea", "india", "singapore",
    "malaysia", "uae", "united arab emirates", "qatar", "egypt", "south africa", "brazil", "mexico",
]
_KNOWN_VENUES = {  # venues whose name carries no city; used only when no city was found
    "royal college of surgeons of england": ("London", "London"),
    "royal society of medicine": ("London", "London"),
    "bma house": ("London", "London"),
    "royal college of physicians": ("London", "London"),
    "royal college of obstetricians": ("London", "London"),
    "goodenough college": ("London", "London"),
}
_COUNTRY_PARTS = {"uk", "u.k.", "united kingdom", "england", "scotland", "wales",
                  "northern ireland", "great britain", "gb"}
_UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
_ONLINE_RE = re.compile(r"\b(online|webinar|virtual|zoom|microsoft teams|ms teams|live ?stream|remote)\b", re.I)


def _text_lines(html: str) -> str:
    """HTML -> plain text, one block per line (no bs4/lxml available)."""
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html or "")
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|tr|h\d|table|ul|ol|section|header|footer|dd|dt)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html_lib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*", "\n", s)
    return s.strip()


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ")).strip()


def _norm_date_text(s: str) -> str:
    s = html_lib.unescape(s or "").replace("\xa0", " ")
    s = s.replace("–", "-").replace("—", "-").replace("‑", "-")
    s = re.sub(r"(?<=\d)\s*(?:st|nd|rd|th)\b", "", s, flags=re.I)
    s = re.sub(r"\b(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?\b\.?", " ", s, flags=re.I)
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm)?\b", " ", s, flags=re.I)
    s = re.sub(r"\b\d{1,2}\s*(?:am|pm)\b", " ", s, flags=re.I)
    s = re.sub(r"\b(?:gmt|bst|utc|uk time)\b", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s)


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_range(text: str, default_year: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
    """Parse the first date or date range in `text` -> (start_iso, end_iso|None).
    Handles '5 Feb 2027 08:00 - 6 Feb 2027', '25 - 27 Nov 2026', '14 Dec 12:05PM - 18 Dec 12:05PM 2026',
    '20 Nov - 21 Nov', 'October 21 (Wed) - 23 (Fri), 2026', '25 th and 26 th Nov 2026'."""
    s = _norm_date_text(text)
    if not s:
        return None, None
    m = _RANGE_RE.search(s)
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        mon2 = _MONTHS[m2.lower()[:3]]
        mon1 = _MONTHS[m1.lower()[:3]] if m1 else mon2
        yr2 = int(y2) if y2 else (int(y1) if y1 and m1 and mon1 == mon2 else None)
        yr2 = yr2 or default_year
        if yr2:
            yr1 = int(y1) if y1 else (yr2 - 1 if mon1 > mon2 else yr2)
            a, b = _mk(yr1, mon1, int(d1)), _mk(yr2, mon2, int(d2))
            if a and b and a <= b:
                return a.isoformat(), (b.isoformat() if b != a else None)
    m = _MF_RANGE_RE.search(s)
    if m:
        mn, d1, d2, y = m.groups()
        yr = int(y) if y else default_year
        if yr:
            a, b = _mk(yr, _MONTHS[mn.lower()[:3]], int(d1)), _mk(yr, _MONTHS[mn.lower()[:3]], int(d2))
            if a and b and a < b:
                return a.isoformat(), b.isoformat()
    m = _SINGLE_RE.search(s)
    if m:
        d1, mn, y = m.groups()
        yr = int(y) if y else default_year
        if yr:
            a = _mk(yr, _MONTHS[mn.lower()[:3]], int(d1))
            if a:
                return a.isoformat(), None
    m = _MF_SINGLE_RE.search(s)
    if m:
        mn, d1, y = m.groups()
        yr = int(y) if y else default_year
        if yr:
            a = _mk(yr, _MONTHS[mn.lower()[:3]], int(d1))
            if a:
                return a.isoformat(), None
    return None, None


def split_location(loc: Optional[str]) -> Dict[str, Any]:
    """Free-text venue line -> event_format / venue_name / city / region."""
    loc = _clean(loc)
    out: Dict[str, Any] = {}
    if not loc:
        return out
    low = loc.lower()
    uk_hit = None
    for key in _UK_REGIONS:
        for m in re.finditer(rf"\b{re.escape(key)}\b", low):
            if uk_hit is None or m.start() >= uk_hit[1]:
                uk_hit = (key, m.start())
    foreign = None
    if uk_hit is None:
        for fc in _FOREIGN_CITIES:
            if re.search(rf"\b{re.escape(fc)}\b", low):
                foreign = fc
                break
    is_online = bool(_ONLINE_RE.search(loc))
    if is_online and uk_hit is None and foreign is None:
        out.update(event_format="online", venue_name=None, city=None, region=None)
        return out
    if is_online and re.search(r"\b(hybrid|in[- ]person|face[- ]to[- ]face)\b", loc, re.I):
        out["event_format"] = "hybrid"
    else:
        out["event_format"] = "in_person"
    city = region = None
    if uk_hit:
        city, region = _UK_REGIONS[uk_hit[0]]
    elif foreign:
        city, region = foreign.title(), "international"
    elif any(k in low for k in _KNOWN_VENUES):
        city, region = next(v for k, v in _KNOWN_VENUES.items() if k in low)
    else:
        segs = [p.strip(" .;") for p in loc.split(",") if p.strip(" .;")]
        us = re.search(r",\s*([A-Z][A-Za-z.' -]{2,30}),\s*(?:A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b", loc)
        if len(segs) >= 2 and segs[-1].lower() in _FOREIGN_COUNTRIES:
            city, region = segs[-2].title(), "international"
        elif us:
            city, region = us.group(1).strip(), "international"
    parts = [p.strip(" .;") for p in re.split(r",|\n|;", _UK_POSTCODE_RE.sub("", loc)) if p.strip(" .;")]
    keep = []
    for p in parts:
        pl = p.lower()
        if (len(p) == 2 and p.isupper()) or pl in _COUNTRY_PARTS or pl in _FOREIGN_COUNTRIES or (city and pl in (city.lower(), uk_hit[0] if uk_hit else "")):
            continue
        keep.append(p)
    venue = ", ".join(keep).strip() or None
    if venue:
        venue = re.sub(r"\s*,\s*([)\]])", r"\1", venue).strip(" ,")
    if venue and city:
        venue = re.sub(rf"[\s,]*(?:\bin\s+)?(?:central\s+)?\b{re.escape(city)}\b\s*$", "", venue, flags=re.I).strip(" ,") or None
    out.update(venue_name=venue[:200] if venue else None, city=city, region=region)
    return out


def find_cpd(text: str) -> Tuple[Optional[int], bool]:
    """(points, accredited) from CPD/CME wording; max points in a window after the keyword."""
    best = None
    for m in re.finditer(r"\b(?:CPD|CME)\b", text or "", re.I):
        win = text[m.start(): m.start() + 260]
        if re.search(r"awaiting|not (?:yet )?(?:been )?(?:approved|accredited)|will be sought|applied for|pending", win, re.I):
            continue
        for n in re.findall(r"(\d{1,3})\s*(?:external\s+)?(?:CPD\s*|CME\s*)?(?:points?|credits?|hours?)", win, re.I):
            if best is None or int(n) > best:
                best = int(n)
        before = text[max(0, m.start() - 80): m.start()]
        for n in re.findall(r"(\d{1,3})\s*(?:external\s+)?$", before):
            if best is None or int(n) > best:
                best = int(n)
    if best is not None:
        return best, True
    if re.search(r"\b(?:CPD|CME)[- ](?:accredited|approved)|accredited for (?:CPD|CME)|approved for (?:CPD|CME)", text or "", re.I):
        return None, True
    return None, False


def truncate_sentence(text: str, max_chars: int = 320) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last = max(cut.rfind(p + " ") for p in (".", "!", "?"))
    if last > max_chars * 0.5:
        return cut[: last + 1].rstrip()
    return cut.rstrip() + "…"


_JUNK_PARA_RE = re.compile(
    r"cookie|javascript|log ?in|sign in|privacy|©|copyright|all rights reserved|skip to|"
    r"click here|register now|download event|add to calendar|back to events|other events|"
    r"register your interest|scheduling 20\d\d|waitlist|waiting list|is now full|sold out|"
    r"registration (?:is )?(?:now )?(?:open|closed)", re.I)


def first_paragraph(text: str, min_len: int = 60) -> Optional[str]:
    """First real prose paragraph (never nav / cookie / legal chrome)."""
    for line in (text or "").split("\n"):
        line = line.strip()
        if (len(line) >= min_len and not _JUNK_PARA_RE.search(line) and line.count(" ") >= 8
                and not re.match(r"^\W*\d", line) and re.search(r"[.!?)\"”]\s*$|\.\s", line)):
            return truncate_sentence(line)
    return None


def llm_soft_fields(llm_call: Callable[[str], Optional[str]], title: str, body: str,
                    specialty_hint: str) -> Dict[str, Any]:
    """ONE small LLM call for description + specialty; caller supplies deterministic backstops."""
    prompt = f"""You are summarising a single medical event page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{(body or '')[:3000]}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. {specialty_hint})" or null
}}"""
    try:
        raw = llm_call(prompt)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"LLM call failed for '{title[:50]}': {e}")
        raw = None
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning(f"soft-field JSON parse failed: {e}; raw[:120]={raw[:120]!r}")
        return {}
    desc = parsed.get("description")
    spec = parsed.get("specialty")
    return {
        "description": desc.strip() if isinstance(desc, str) and desc.strip() else None,
        "specialty": spec.strip() if isinstance(spec, str) and spec.strip() else None,
    }


def event_type_from_title(title: str, default: str = "conference") -> str:
    t = title or ""
    if re.search(r"\b(?:masterclass|workshop|webinar|seminar|study day|training day|teaching day|skills lab|simulation|"
                 r"bootcamp|boot camp|viva|dinner)\b", t, re.I):
        return "workshop"
    if re.search(r"\b(?:course|programme|certificate|diploma)\b", t, re.I):
        return "course"
    if re.search(r"\b(?:conference|congress|symposium|summit|annual meeting|scientific meeting|meeting|forum|"
                 r"retreat|masterclass day|expo)\b", t, re.I):
        return "conference"
    return default


def _price_of(s: str) -> Optional[float]:
    m = re.search(r"£\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def make_tier(label: str, price: float, *, currency: str = "GBP", early: bool = False,
              deadline: Optional[str] = None) -> Dict[str, Any]:
    if len(label) > 120:  # keep both ends: the category start and the timeframe / band suffix
        label = label[:62].rstrip(" ·-/") + " … " + label[-54:].lstrip(" ·-/")
    return {"tier_label": label, "price_gbp": price, "currency": currency,
            "is_early_bird": early, "early_bird_deadline": deadline}


def dedupe_tiers(tiers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for t in tiers:
        k = (t["tier_label"], t["price_gbp"], t.get("currency"))
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def matrix_tiers(html: str, *, section_default: str = "Registration", currency: str = "GBP") -> List[Dict[str, Any]]:
    """Fee tables whose header row has >=1 price COLUMNS (e.g. 'Full meeting' | 'One day').
    One tier per price cell: '<Section> · <row> · <column>'. Falls back to nothing when a
    table has no £ cells. The shared parse_pricing_tables keeps only the LAST column for
    non-timeframe headers, which silently drops the full-meeting rates."""
    tiers: List[Dict[str, Any]] = []
    for tm in re.finditer(r"(?is)<table[^>]*>(.*?)</table>", html or ""):
        rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tm.group(1))
        grid = []
        for r in rows:
            cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)
            grid.append([re.sub(r"\s*\n\s*", " / ", _text_lines(c)).strip(" /") for c in cells])
        if len(grid) < 2:
            continue
        header = grid[0]
        if any(_price_of(c) for c in header):
            continue  # no header row of column names
        section = section_default
        if header and re.search(r"(?i)rate|fee|registration|price|ticket", header[0] or ""):
            section = header[0].strip()
        for row in grid[1:]:
            if len(row) < 2 or not row[0]:
                continue
            for ci in range(1, len(row)):
                price = _price_of(row[ci])
                if price is None:
                    continue
                col = header[ci].strip() if ci < len(header) else ""
                label = " · ".join(x for x in (section, row[0], col) if x)
                early = bool(re.search(r"(?i)early", f"{section} {col}"))
                tiers.append(make_tier(label, price, currency=currency, early=early))
    return dedupe_tiers(tiers)


def find_registration_link(html: str, base_url: str) -> Optional[str]:
    """First 'Register' / 'Book online' style link (organiser_url candidate)."""
    for m in re.finditer(r'(?is)<a\b([^>]*)>(.*?)</a>', html or ""):
        attrs, inner = m.group(1), _clean(m.group(2))
        hm = re.search(r'href="([^"#][^"]*)"', attrs)
        tm = re.search(r'title="([^"]*)"', attrs)
        if not hm:
            continue
        href = html_lib.unescape(hm.group(1))
        if re.match(r"(?i)(?:mailto:|tel:|javascript:)", href) or "/add" == href[-4:]:
            continue
        label = f"{inner} {tm.group(1) if tm else ''}"
        if re.search(r"(?i)\b(?:register|registration|book online|book now|book here|buy tickets?|reserve)\b", label):
            return urljoin(base_url, href)
    return None


def rowspan_tiers(html: str, *, currency: str = "GBP") -> List[Dict[str, Any]]:
    """Fee tables that use rowspan for the band cell (Early Bird / Standard) with a
    category and a price cell per row. '<Registration> · <band> · <category>'."""
    tiers: List[Dict[str, Any]] = []
    for tm in re.finditer(r"(?is)<table[^>]*>(.*?)</table>", html or ""):
        if "rowspan" not in tm.group(1).lower():
            continue
        grid: List[List[str]] = []
        carry: Dict[int, Tuple[str, int]] = {}
        for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tm.group(1)):
            cells = re.findall(r"(?is)<t[dh]([^>]*)>(.*?)</t[dh]>", r)
            out: List[str] = []
            col, k = 0, 0
            while k < len(cells) or col in carry:
                if col in carry:
                    txt, rem = carry[col]
                    out.append(txt)
                    if rem <= 1:
                        del carry[col]
                    else:
                        carry[col] = (txt, rem - 1)
                    col += 1
                    continue
                attrs, inner = cells[k]
                k += 1
                txt = _text_lines(inner)
                rs = re.search(r'rowspan="(\d+)"', attrs, re.I)
                if rs and int(rs.group(1)) > 1:
                    carry[col] = (txt, int(rs.group(1)) - 1)
                out.append(txt)
                col += 1
            grid.append(out)
        for row in grid:
            pcols = [i for i, c in enumerate(row) if _price_of(c) is not None]
            if not pcols:
                continue
            pi = pcols[-1]
            price = _price_of(row[pi])
            cat = _clean(row[pi - 1]) if pi >= 1 else ""
            band_cells = [c for c in row[: max(pi - 1, 0)] if c.strip()]
            band, deadline = "", None
            if band_cells:
                lines = [l.strip() for l in band_cells[0].split("\n") if l.strip()]
                band = lines[0] if lines else ""
                for l in lines[1:]:
                    if re.search(r"(?i)until|by|before|deadline", l):
                        d, _ = parse_date_range(l)
                        deadline = d or deadline
            early = bool(re.search(r"(?i)early", band))
            label = " · ".join(x for x in ("Registration", band, cat) if x)
            tiers.append(make_tier(label, price, currency=currency, early=early,
                                   deadline=deadline if early else None))
    return dedupe_tiers(tiers)


def refine_event_type(title: str, body: str, current: str) -> str:
    """The title heuristic defaults to 'conference'. When the title carries no type word at all,
    let the first lines of the page decide (course / workshop); never override an explicit title cue."""
    if current != "conference" or re.search(
            r"(?i)\b(?:conference|congress|symposium|summit|annual meeting|scientific meeting|meeting|forum|"
            r"course|workshop|webinar|masterclass|seminar|study day|training day)\b", title or ""):
        return current
    head = (body or "")[:700]
    if re.search(r"(?i)\b(?:webinar|masterclass|workshop|training day|study day|skills (?:day|session)|hands-on)\b", head):
        return "workshop"
    if re.search(r"(?i)\b(?:this|the|a|our)\s+(?:\w+\s+){0,3}?course\b|\bcadaveric\b|exam(?:ination)? preparation|FRCS", head):
        return "course"
    return current


def ticket_tiers(html: str, *, currency: str = "GBP") -> List[Dict[str, Any]]:
    """Ticket tables with a header like [Ticket | Category | Price]: '<Ticket> · <Category>'
    (the shared parser keeps only the first column and so collapses categories)."""
    tiers: List[Dict[str, Any]] = []
    for tm in re.finditer(r"(?is)<table[^>]*>(.*?)</table>", html or ""):
        rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tm.group(1))
        grid = [[_clean(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)] for r in rows]
        if len(grid) < 2 or len(grid[0]) < 2 or not re.search(r"(?i)price|cost|fee", grid[0][-1] or ""):
            continue
        for row in grid[1:]:
            if len(row) < 2:
                continue
            price = _price_of(row[-1])
            cells = [c for c in row[:-1] if c]
            if price is None or not cells:
                continue
            if len(cells) == 1:
                cells = ["Registration", re.sub(r"\s*[-–]\s*Registration\s*$", "", cells[0]).strip()]
            label = " · ".join(cells)
            tiers.append(make_tier(label, price, currency=currency, early=bool(re.search(r"(?i)early", label))))
    return dedupe_tiers(tiers)


def rate_line_tiers(text: str, default_year: Optional[int] = None) -> List[Dict[str, Any]]:
    """Prose fee lines: 'Early-bird rate: £310 (until midnight on 27 September)', 'Standard rate: £395 (from 28 September)'."""
    tiers: List[Dict[str, Any]] = []
    for line in (text or "").split("\n"):
        m = re.match(r"^\s*([A-Za-z][A-Za-z \-/&']{2,50}?)\s*:\s*£\s*([\d,]+(?:\.\d+)?)\s*(?:\((.*?)\))?", line)
        if not m or re.search(r"(?i)deposit|purchase order|membership|per annum", m.group(1)):
            continue
        label = re.sub(r"(?i)\s+rate$", "", m.group(1)).strip()
        early = bool(re.search(r"(?i)early", label))
        deadline = None
        if early and m.group(3) and re.search(r"(?i)until|before|by", m.group(3)):
            d, _ = parse_date_range(m.group(3), default_year)
            deadline = d
        tiers.append(make_tier(f"Registration · {label}", float(m.group(2).replace(",", "")),
                               early=early, deadline=deadline))
    return dedupe_tiers(tiers)


def external_fee_hop(body_html: str, browser: Any, own_host: str, *, max_links: int = 2) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Coverage patterns #2/#5: no fees on the event page, but a 'Book online' / 'Register' / 'Further details'
    link leads to the organiser's own site. Read at most `max_links` such pages (and one 'Registration / fees'
    nav link on them). Returns (tiers, link_used)."""
    seen: List[str] = []
    for m in re.finditer(r'(?is)<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', body_html or ""):
        href, label = html_lib.unescape(m.group(1)), _clean(m.group(2))
        if (host_is(href, own_host) or any(host_is(href, d) for d in _SOCIAL_HOSTS)
                or re.search(r"(?i)\.pdf(?:\?|$)", href) or href in seen):
            continue
        if re.search(r"(?i)regist|book|ticket|fees?|further details|more information|visit|website|here", label) or label == href:
            seen.append(href)
    for link in seen[:max_links]:
        ext = ext_get(link)
        if not ext:
            continue
        tiers = matrix_tiers(ext) or ticket_tiers(ext) or list(parse_pricing_tables(ext, default_currency="GBP"))
        if tiers:
            return _tidy_hop_labels(dedupe_tiers(tiers)), link
        for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>\s*([^<]{3,60}?)\s*</a>', ext):
            if re.search(r"(?i)^regist\w*(?: and| &amp;| &)? ?(?:fees?)?$|^fees?$|registration (?:and|&amp;) fees|^book (?:now|tickets)$", text.strip()):
                sub = ext_get(urljoin(link, html_lib.unescape(href)))
                if sub:
                    tiers = matrix_tiers(sub) or ticket_tiers(sub) or list(parse_pricing_tables(sub, default_currency="GBP"))
                    if tiers:
                        return _tidy_hop_labels(dedupe_tiers(tiers)), link
                break
    return [], None


def _tidy_hop_labels(tiers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The shared table parser sometimes takes a nearby sentence ('Registration fees do not include …')
    as the section name; swap such headings for a plain 'Registration'."""
    for t in tiers:
        t["tier_label"] = re.sub(r"^[^·]*(?:do not include|not included|exclud|vat|manage your)[^·]*·", "Registration ·",
                                 t["tier_label"], flags=re.I)
    return tiers


def deposit_tiers(text: str) -> List[Dict[str, Any]]:
    """'£49 registration deposit, which is refunded …' / 'a deposit of £40' -> one refundable-deposit tier."""
    m = (re.search(r"£\s*(\d+(?:\.\d+)?)\s+(?:refundable\s+)?(?:registration\s+)?deposit", text or "", re.I)
         or re.search(r"deposit of £\s*(\d+(?:\.\d+)?)", text or "", re.I))
    if not m:
        return []
    return [make_tier("Refundable deposit", float(m.group(1)))]


def says_free(text: str) -> bool:
    return bool(re.search(r"(?i)\b(?:free to attend|free of charge|free event|free webinar|no registration fee|no charge)\b", text or ""))


_ITEM_RE = re.compile(
    r'<div class="item">.*?<h4><a href="([^"]+)">(.*?)</a></h4>.*?<small>([^<]*)</small>', re.S)


class BBTSExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        today = date.today()
        html = fetch_html(LISTING_URL, browser=browser, expect_selector=".item")
        if not html:
            logger.warning("BBTS: events feed fetch failed")
            return None

        pages = [html]
        cur_ym = f"{today.year}-{today.month:02d}"
        months = sorted({m for m in re.findall(r"\?month=(\d{4}-\d{2})", html) if m >= cur_ym})
        for ym in months[:6]:
            mh = fetch_html(MONTH_URL.format(ym=ym), browser=browser, expect_selector=".item")
            if mh:
                pages.append(mh)

        shells: Dict[str, Dict[str, Any]] = {}
        for ph in pages:
            items = _ITEM_RE.findall(ph)
            self._items_seen = getattr(self, "_items_seen", 0) + len(items)
            for href, raw_title, small in items:
                if "/events/bbts_events/" not in href:
                    continue
                title = _clean(raw_title)
                start, _ = parse_date_range(small)
                if not title or not start or date.fromisoformat(start) < today:
                    continue
                if re.search(r"(?i)cancel|postponed", title):
                    continue
                url = urljoin(BASE_URL, html_lib.unescape(href))
                shells.setdefault(url, {
                    "title": title, "booking_url": url, "start_date": start,
                    "event_type": event_type_from_title(title, "conference"),
                })

        conf = self._annual_conference_shell(today, browser)
        if conf:
            shells.setdefault(conf["booking_url"], conf)

        out = sorted(shells.values(), key=lambda s: s["start_date"])
        logger.info(f"BBTS: {len(out)} upcoming event shells")
        if not out and getattr(self, "_items_seen", 0):
            self.verified_empty = "events feed answered 200; no upcoming /events/bbts_events/ items"
        return out

    def _annual_conference_shell(self, today: date, browser: Any) -> Optional[Dict[str, Any]]:
        html = fetch_html(CONFERENCE_PAGE, browser=browser)
        if not html:
            return None
        text = _text_lines(html)
        m = re.search(r"(?i)(BBTS Annual Conference\s+(\d{4}))\s+will take place\s+(?:at|in)\s+([^.]*?)\s+from\s+([^.]*?)\.", text)
        if not m:
            return None
        year = int(m.group(2))
        start, end = parse_date_range(m.group(4), year)
        if not start or date.fromisoformat(end or start) < today:
            return None
        shell = {"title": m.group(1).strip(), "booking_url": CONFERENCE_PAGE, "start_date": start,
                 "event_type": "conference", "location_hint": _clean(m.group(3))}
        if end:
            shell["end_date"] = end
        return shell

    # ------------------------------------------------------------------ #
    # Detail
    # ------------------------------------------------------------------ #
    def extract_detail(self, page: Page, shell: Dict[str, Any],
                       llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        url = shell.get("booking_url") or ""
        browser = getattr(self, "browser", None)
        html = fetch_html(url, browser=browser, loaded_page=page) if url else None
        if not html:
            try:
                html = page.content()
            except Exception:
                html = None
        if not html:
            logger.warning(f"BBTS: no HTML for {url}")
            return result

        cm = re.search(r'<div class="col-md-9 col-xs-12">(.*?)<blog-comments', html, re.S)
        content_html = cm.group(1) if cm else html
        content_html = re.sub(r'data:image/[^"\')\s]+', "", content_html)
        body = _text_lines(content_html)
        hm = re.search(r"<h[12][^>]*>(.*?)</h[12]>", content_html, re.S)
        title = shell.get("title") or (_clean(hm.group(1)) if hm else "")
        result["conference_name"] = title

        # Dates: the feed gives the first day; the body supplies the range.
        year = int(shell["start_date"][:4]) if shell.get("start_date") else None
        start, end = parse_date_range(body, year)
        if start and start == shell.get("start_date") and end:
            result["end_date"] = end
        elif not start and shell.get("end_date"):
            result["end_date"] = shell["end_date"]

        venue_line = None
        vm = re.search(r"(?im)^\s*Venue:\s*(.+)$", body)
        if vm:
            venue_line = vm.group(1).strip()
        elif shell.get("location_hint"):
            venue_line = shell["location_hint"]
        if venue_line:
            loc = split_location(venue_line)
            result.update(loc)
        elif re.search(r"(?i)\b(?:virtual|online|webinar)\b", body[:400] + " " + title):
            result.update(event_format="online", venue_name=None, city=None, region=None)

        pts, accredited = find_cpd(body)
        result["cpd_points"] = pts
        result["cpd_accredited"] = accredited

        result["pricing_tiers"] = self._fees(content_html, body, url, browser)

        result["event_type"] = refine_event_type(title, body, shell.get("event_type") or "conference")
        para = first_paragraph(body, 80)
        if len(body) >= 150:
            soft = llm_soft_fields(llm_call, title, body, "Transfusion Medicine, Haematology, Laboratory Medicine")
        else:
            soft = {}
        compact = " ".join(l.strip() for l in body.split("\n")
                           if l.strip() and not re.match(r"(?i)^(?:register|find out more|website:)", l.strip()))[:300]
        result["description"] = soft.get("description") or para or (compact if len(compact) >= 25 else None)
        result["specialty"] = soft.get("specialty") or DEFAULT_SPECIALTY
        return result

    # ------------------------------------------------------------------ #
    def _fees(self, content_html: str, body: str, url: str, browser: Any) -> List[Dict[str, Any]]:
        tiers = list(parse_pricing_tables(content_html, default_currency="GBP")) or matrix_tiers(content_html)
        if tiers:
            return dedupe_tiers(tiers)
        # One hop: "REGISTER HERE" / "Find out more" links to the organiser's own page.
        for href, text in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', content_html, re.S):
            if re.search(r"(?i)regist|book|ticket", _clean(text)) and not host_is(href, "bbts.org.uk"):
                ext = ext_get(href)
                if ext:
                    t = list(parse_pricing_tables(ext, default_currency="GBP")) or matrix_tiers(ext)
                    if t:
                        return dedupe_tiers(t)
                break
        return []
