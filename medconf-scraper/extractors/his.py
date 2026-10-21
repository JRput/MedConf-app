"""
Healthcare Infection Society (HIS) — events extractor.

Platform: Umbraco, server-rendered. The Events Diary
(https://www.his.org.uk/training-events/events-diary/) is ONE page of ~20
`div.linkbox` cards (no real pagination: `?page=N` returns the same page). A
card holds `linkbox-datetype` ("05 November 2026" + a `location-tag` span, or
"24 November 2026 - 26 November 2026 Glasgow", or month-only "March 2027" for
the blended Foundation course), the title and a "More" link. The diary lists
past items too, so everything before today is dropped. Titles carry a
"SOLD OUT - " / "COURSE FULL - " prefix, which is stripped into is_sold_out.

The flagship HIS Annual Conference (HISCON 2027, 8-9 June 2027) is NOT in the
diary; it is found via /training-events/our-conferences/ and added when its
dates are in the future. Its header reads "08 June 2027 - 09 June 2026" (a typo
in the end year) so the end date is repaired from the page's own sentence
"8-9 June 2027".

Detail pages are tabbed through a side menu of real sub-pages (Programme,
Venue, "Registration", "Fees and payment", …). Fees are on the sub-page whose
menu text mentions registration / fees (coverage pattern #4), as a vertical
list (Early Bird … HIS Members £125 … Non members £250) or as prose
("HIS members: £600  Non-members: £750") on the main page.
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

BASE_URL = "https://www.his.org.uk"
LISTING_URL = "https://www.his.org.uk/training-events/events-diary/"
CONFERENCES_URL = "https://www.his.org.uk/training-events/our-conferences/"
DEFAULT_SPECIALTY = "Infection Prevention and Control"

# URL section -> event_type (webinars/training days are short focused sessions;
# the multi-day named courses are courses; the conference pages are conferences).
_SECTION_TYPE = [
    ("/upcoming-webinars/", "workshop"),
    ("/ipc-partners-insight-webinars/", "workshop"),
    ("/webinars/", "workshop"),
    ("/trainee-education-programme/", "workshop"),
    ("/hisukhsa-foundation-course/", "course"),
    ("/water-safety-in-healthcare/", "course"),
    ("/outbreaks-training-course/", "course"),
    ("/ipc-leaders-development-programme/", "course"),
    ("/annual-conference/", "conference"),
    ("/fis-his/", "conference"),
    ("/building-safer-hospitals", "conference"),
]
_SOLD_OUT_RE = re.compile(r"^\s*(?:SOLD OUT|COURSE FULL|FULLY BOOKED|FULL)\s*[-–:]\s*", re.I)

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


class HISExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        today = date.today()
        html = fetch_html(LISTING_URL, browser=browser, expect_selector=".linkbox")
        if not html:
            logger.warning("HIS: events diary fetch failed")
            return None

        shells: List[Dict[str, Any]] = []
        seen = set()
        cards = re.split(r'<div class="linkbox">', html)[1:]
        for card in cards:
            shell = self._parse_card(card, today, browser)
            if shell and shell["booking_url"] not in seen:
                seen.add(shell["booking_url"])
                shells.append(shell)

        # Flagship conferences that the diary does not list (HISCON 2027).
        chtml = fetch_html(CONFERENCES_URL, browser=browser)
        if chtml:
            for href in re.findall(r'<a href="(/training-events/[^"]+)" title="[^"]*"', chtml):
                url = urljoin(BASE_URL, href)
                if url in seen:
                    continue
                shell = self._shell_from_detail(url, today, browser)
                if shell:
                    seen.add(url)
                    shells.append(shell)

        shells.sort(key=lambda s: s.get("start_date") or "")
        logger.info(f"HIS: {len(shells)} upcoming shells")
        if not shells and cards:
            self.verified_empty = "events diary answered 200 and lists no upcoming events"
        return shells

    def _etype(self, url: str, title: str) -> str:
        for frag, kind in _SECTION_TYPE:
            if frag in url:
                return kind
        return event_type_from_title(title, "conference")

    def _parse_card(self, card: str, today: date, browser: Any) -> Optional[Dict[str, Any]]:
        link = re.search(r'<a href="([^"]+)">More</a>', card)
        tt = re.search(r'linkbox-title">(.*?)</div>', card, re.S)
        dt = re.search(r'linkbox-datetype">(.*?)</div>', card, re.S)
        if not (link and tt and dt):
            return None
        url = urljoin(BASE_URL, html_lib.unescape(link.group(1)))
        raw_title = _clean(tt.group(1))
        sold_out = bool(_SOLD_OUT_RE.match(raw_title))
        title = _SOLD_OUT_RE.sub("", raw_title).strip()
        parts = re.split(r"<br\s*/?>", dt.group(1), maxsplit=1)
        date_text = _clean(parts[0])
        location = _clean(parts[1]) if len(parts) > 1 else ""
        if re.search(r"(?i)cancel|postponed", title):
            return None
        start, end = parse_date_range(date_text, today.year)
        desc = tt and re.search(r'linkbox-description">(.*?)</div>', card, re.S)
        shell: Dict[str, Any] = {"title": title, "booking_url": url,
                                 "event_type": self._etype(url, title)}
        if sold_out:
            shell["is_sold_out"] = True
        if location:
            shell["location_hint"] = location
        if desc and _clean(desc.group(1)):
            shell["description_hint"] = _clean(desc.group(1))[:300]
        if start:
            if date.fromisoformat(end or start) < today:
                return None
            shell["start_date"] = start
            if end:
                shell["end_date"] = end
            return shell
        # Month-only cards ("March 2027", blended Foundation course): the live-session dates are on the page.
        if re.fullmatch(r"(?i)[a-z]+\s+\d{4}", date_text):
            dd = self._shell_from_detail(url, today, browser, base=shell)
            return dd
        return None

    def _shell_from_detail(self, url: str, today: date, browser: Any,
                           base: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        html = fetch_html(url, browser=browser)
        if not html:
            return None
        info = self._read_page(html)
        title = info["title"] or (base or {}).get("title")
        start, end = info["start"], info["end"]
        if not start:
            # course pages: "15-19 March 2027 - Live online sessions"
            start, end = self._live_session_dates(info["body"], today.year)
        if not title or not start or date.fromisoformat(end or start) < today:
            return None
        shell = dict(base or {})
        shell.update(title=re.sub(_SOLD_OUT_RE, "", title).strip(), booking_url=url, start_date=start,
                     event_type=(base or {}).get("event_type") or self._etype(url, title))
        if end:
            shell["end_date"] = end
        if info["location"] and not shell.get("location_hint"):
            shell["location_hint"] = info["location"]
        return shell

    @staticmethod
    def _live_session_dates(body: str, year: int) -> Tuple[Optional[str], Optional[str]]:
        for line in body.split("\n"):
            if re.search(r"(?i)live online|live sessions|workshops?", line) and re.search(r"\d", line):
                s, e = parse_date_range(line, year)
                if s:
                    return s, e
        return None, None

    # ------------------------------------------------------------------ #
    # Detail page reading
    # ------------------------------------------------------------------ #
    def _read_page(self, html: str) -> Dict[str, Any]:
        hd = re.search(r'event-detail-header-datetype">(.*?)</div>', html, re.S)
        tt = re.search(r'event-detail-header-title">(.*?)</div>', html, re.S)
        uc = re.search(r'<div class="usercontent">(.*)', html, re.S)
        body_html = uc.group(1) if uc else ""
        body_html = re.split(r"(?:See all events|Join us on social media)", body_html)[0]
        body = _text_lines(body_html)
        date_text, location = "", ""
        if hd:
            loc_m = re.search(r'tag-location">(.*?)</span>', hd.group(1), re.S)
            location = _clean(loc_m.group(1)) if loc_m else ""
            date_text = _clean(re.sub(r'<span class="tag-location">.*?</span>', " ", hd.group(1), flags=re.S))
        else:
            # FIS / HISCON template: dates sit at the top of .textpage-content
            tc = re.search(r'textpage-content">(.*?)(?:<h\d|<div class="usercontent")', html, re.S)
            if tc:
                raw = tc.group(1)
                lm = re.search(r'tag-location">(.*?)</span>', raw, re.S)
                date_text = _clean(re.sub(r"<span[^>]*>.*?</span>", " ", raw, flags=re.S))
                location = _clean(lm.group(1)) if lm else ""
                if not location:
                    # "... 09 June 2026 RCP London (Royal College of Physicians)": keep text after the last year
                    lm2 = re.search(r"\d{4}\s+(?!-)([A-Z].+)$", date_text)
                    if lm2:
                        location = lm2.group(1).strip()
                        date_text = date_text[: lm2.start(1)].strip()
        year_hint = date.today().year
        start, end = parse_date_range(date_text, year_hint)
        if start and (not end or end < start):
            end = None
            # header typo (HISCON: "08 June 2027 - 09 June 2026"): repair from the first sentences
            s2, e2 = parse_date_range(body[:900], int(start[:4]))
            if s2 == start and e2:
                end = e2
        title = _clean(tt.group(1)) if tt else ""
        if not title:
            h = re.search(r"<title>(.*?)</title>", html, re.S)
            title = _clean(h.group(1)).split("|")[0].split(" - ")[0].strip() if h else ""
        menu = re.search(r'sidemenu-menu">(.*?)</ul>', html, re.S)
        links = re.findall(r'<a href="([^"]+)">([^<]*)</a>', menu.group(1)) if menu else []
        return {"title": title, "start": start, "end": end, "location": location,
                "body": body, "body_html": body_html, "menu": links}

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
            logger.warning(f"HIS: no HTML for {url}")
            return result
        info = self._read_page(html)
        body, body_html = info["body"], info["body_html"]
        title = _SOLD_OUT_RE.sub("", info["title"] or shell.get("title") or "").strip()
        if title:
            result["conference_name"] = title
        if _SOLD_OUT_RE.match(info["title"] or "") or shell.get("is_sold_out"):
            result["is_sold_out"] = True

        if info["start"]:
            result["start_date"] = info["start"]
            if info["end"]:
                result["end_date"] = info["end"]
        else:
            s, e = self._live_session_dates(body, date.today().year)
            if s:
                result["start_date"] = s
                if e:
                    result["end_date"] = e
        loc_line = info["location"] or shell.get("location_hint") or ""
        loc = split_location(loc_line)
        if loc:
            result.update(loc)
            if loc.get("event_format") == "online":
                result["venue_name"] = None

        # Fees: registration / fees sub-page first, then prose on the page itself.
        tiers: List[Dict[str, Any]] = []
        pages = [(body_html, body)]
        for href, text in info["menu"]:
            if re.search(r"(?i)regist|fees?|booking|payment", text) and not re.search(r"(?i)sponsor|exhibit|abstract", text):
                sub_url = urljoin(BASE_URL, html_lib.unescape(href))
                if sub_url.rstrip("/") == url.rstrip("/"):
                    continue
                shtml = fetch_html(sub_url, browser=browser)
                if shtml:
                    sinfo = self._read_page(shtml)
                    pages.insert(0, (sinfo["body_html"], sinfo["body"]))
                break
        for h, t in pages:
            tiers = self._fees(h, t)
            if tiers:
                break
        if not tiers and ("/fis-his/" in url or any(host_is(u, "fisconference.org") for u in re.findall(r'href="(https?://[^"]+)"', body_html))):
            tiers, organiser = self._two_hop_fees(body_html, browser)
            if organiser:
                result["organiser_url"] = organiser
        result["pricing_tiers"] = tiers

        all_text = "\n".join(t for _, t in pages)
        pts, accredited = find_cpd(all_text)
        result["cpd_points"] = pts
        result["cpd_accredited"] = accredited

        soft = llm_soft_fields(llm_call, title, body, "Infection Prevention and Control, Microbiology, Infectious Diseases")
        result["description"] = soft.get("description") or first_paragraph(body) or shell.get("description_hint")
        result["specialty"] = soft.get("specialty") or DEFAULT_SPECIALTY
        return result

    # ------------------------------------------------------------------ #
    def _fees(self, body_html: str, body: str) -> List[Dict[str, Any]]:
        tiers = (rowspan_tiers(body_html) or list(parse_pricing_tables(body_html, default_currency="GBP"))
                 or matrix_tiers(body_html))
        if tiers:
            return dedupe_tiers(tiers)
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        # 1. vertical list: [Section] / Available until D / Category / £N …
        section, deadline, prev = None, None, None
        for line in lines:
            if re.fullmatch(r"£\s*[\d,]+(?:\.\d+)?", line):
                if prev:
                    early = bool(section and re.search(r"(?i)early", section))
                    label = " · ".join(x for x in ("Registration", section, prev) if x)
                    tiers.append(make_tier(label, _price_of(line) or 0.0, early=early,
                                           deadline=deadline if early else None))
                prev = None
                continue
            if re.match(r"(?i)^available until", line):
                d, _ = parse_date_range(line, date.today().year)
                deadline = d
                continue
            if re.match(r"(?i)^(?:super[- ])?early[- ]bird$|^standard$|^late$|^regular$|^on[- ]?site$|^full(?: rate)?$", line):
                section, deadline, prev = line.title() if line.isupper() else line, None, None
                continue
            if len(line) < 70:
                prev = line
        if tiers:
            return dedupe_tiers(tiers)
        # 2. prose: "HIS members: £600", "Non-members : £750"
        for line in lines:
            m = re.match(r"^([A-Za-z][A-Za-z /&\-]{2,50}?)\s*:\s*£\s*([\d,]+(?:\.\d+)?)\b", line)
            if m and not re.search(r"(?i)purchase order|deposit", m.group(1)):
                tiers.append(make_tier(f"Delegate fees · {m.group(1).strip()}", float(m.group(2).replace(",", ""))))
        if not tiers and re.search(r"(?i)\bfree to attend\b|\bis free\b|free of charge", body):
            tiers.append(make_tier("Registration · Free", 0.0))
        return dedupe_tiers(tiers)

    # ------------------------------------------------------------------ #
    def _two_hop_fees(self, body_html: str, browser: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Conference pages that only link out (FIS 2026 -> fisconference.org -> fitwise.eventsair.com/fis-2026
        -> /registration-and-fees). Coverage pattern #5. Returns (tiers, organiser_url)."""
        hops = [h for h in re.findall(r'href="(https?://[^"]+)"', body_html)
                if not (host_is(h, "his.org.uk") or any(host_is(h, d) for d in _SOCIAL_HOSTS))]
        if not hops:
            return [], None
        organiser = hops[0]
        hop1 = ext_get(organiser)
        if not hop1:
            return [], organiser
        site_url, site_html = organiser, hop1
        ea = re.findall(r'href="(https?://[^"]*eventsair\.com/[^"]+)"', hop1)
        ea = [u for u in ea if host_is(u, "eventsair.com") and re.search(r"/[a-z0-9-]*20\d\d[a-z0-9-]*/?$", u.split("?")[0], re.I)]
        if ea:
            years = (str(date.today().year), str(date.today().year + 1))
            site_url = ([u for u in ea if any(y in u for y in years)] or ea)[-1]
            site_html = ext_get(site_url) or ""
        base = site_url.rstrip("/") + "/"
        for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>\s*([^<]{3,60}?)\s*</a>', site_html or ""):
            if re.search(r"(?i)regist\w*(?: and| &amp;| &)? ?fees?|^fees|^registration$", text):
                fee_html = ext_get(urljoin(base, html_lib.unescape(href)))
                if fee_html:
                    t = matrix_tiers(fee_html) or list(parse_pricing_tables(fee_html, default_currency="GBP"))
                    if t:
                        return dedupe_tiers(t), site_url
                break
        return [], site_url if site_url != organiser else organiser
