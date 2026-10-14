"""Shared base for sources that are ONE recurring congress' official website.

Examples: ESPID 2027, DDW 2027, ECR 2027. Each source yields one upcoming
edition (the homepage, or the edition microsite it links to), never a list.

Flow
  list_shells_override : read HOME_URL (httpx, Playwright fallback via
                         fetch_html) -> upcoming edition from, in order of trust,
                         JSON-LD Event -> dated header line ("7-9 June 2027 |
                         Liverpool") -> og:description. When the homepage still
                         shows a past edition, follow links whose text names a
                         later year ("Go to EAPS 2027"). No upcoming edition ->
                         empty listing (never an invented edition).
  extract_detail       : edition page text -> place/format/description; ONE hop
                         to the site's own Registration/Fees page(s) for prices
                         and to Abstracts / Call-for-papers / Key-dates pages for
                         the abstract deadline.

Subclasses are constants (HOME_URL, SOCIETY, EVENT_NAME, DEFAULT_SPECIALTY,
DEFAULT_CURRENCY, optional REG_URLS / ABSTRACT_URLS / EDITION_URLS) plus, where a
site needs it, one small hook (`parse_place`, `edition_title`, `fees_from_pages`).
"""
import html as _html
import json
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from logger import logger

from .abstract_classifier import classify_submission
from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .specialty_classifier import classify_specialty
from .tribe_events import clip_venue, html_to_lines, pick_description
from .wordpress_generic import (
    _DETAIL_CHROME_RE, _meta, dedupe_consecutive, find_dates, json_ld_events,
    location_from_ld, split_location, _COUNTRIES, _VENUE_KW_RE, tiers_from_offers,
)

# ── text helpers ────────────────────────────────────────────────────────────

_MONTHS_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_AMP_DAYS_RE = re.compile(rf"\b(\d{{1,2}})\s*(?:&|and)\s*(\d{{1,2}})(\s+{_MONTHS_RE}\b)", re.I)
_YEARLESS_RANGE_RE = re.compile(rf"(?<![\d,])\b(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})\s+({_MONTHS_RE})\b(?!\s*,?\s*\d{{4}})", re.I)
_YEARLESS_RANGE_US_RE = re.compile(rf"\b({_MONTHS_RE})\s+(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})\b(?!\s*,?\s*\d{{4}})", re.I)
_SEP_RE = re.compile(r"\s*[|·•]\s*")
# A date line that is a deadline / registration milestone / on-demand access, not the congress itself.
_NOT_EVENT_SEG_RE = re.compile(
    r"\b(?:deadline|abstracts?|submission|submit|notification|registration|register|opens?|closes?|closing|until|before|late[\s-]breaking|"
    r"early|on[\s-]demand|webcast|replay|summer school|webinar|volunteer|scholarship|call for|apply|application|membership|"
    r"posted|published|updated|released?|cancell?ation)\b", re.I)
_SOCIAL_RE = re.compile(r"facebook|twitter|x\.com|linkedin|instagram|youtube|tiktok|whatsapp|mailto:|tel:", re.I)
_ONLINE_TAIL_RE = re.compile(r"\s*(?:&|\+|and|\|)\s*(?:online|virtual|digital)\b\.?", re.I)
_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "D.C.": "District of Columbia",
}
_STATE_NAMES = {v.lower() for v in _US_STATES.values()}
_PLACE_STOP_RE = re.compile(
    r"^(?:register|book|days?|hours?|minutes?|seconds?|attendees?|speakers?|exhibitors?|learn more|read more|menu|home|about|"
    r"contact|more information|watch|sign up|submit|join|apply|login|log in|search|skip)\b", re.I)


def html_lines(html: str) -> List[str]:
    lines = html_to_lines(_DETAIL_CHROME_RE.sub(" ", html or ""))
    return dedupe_consecutive([l for l in (re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", x).strip() for x in lines) if l])


def norm_dates(text: str, year: Optional[int] = None) -> str:
    """"14 & 15 October 2027" -> "14-15 October 2027"; yearless "16-19 September" gets `year` appended."""
    t = _AMP_DAYS_RE.sub(r"\1-\2\3", text or "")
    if year:
        m = _YEARLESS_RANGE_RE.search(t)
        if m:
            t = t[:m.end()] + f" {year}" + t[m.end():]
        else:
            m = _YEARLESS_RANGE_US_RE.search(t)
            if m:
                t = t[:m.end()] + f", {year}" + t[m.end():]
    return t


def page_year(html: str, lines: List[str], url: str, today: date) -> Optional[int]:
    """Edition year an edition page names in its <title>/URL/first lines (>= this year), for yearless date lines."""
    t = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    for src in (_html.unescape(t.group(1)) if t else "", url, " ".join(lines[:12])):
        for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", src):
            if int(y) >= today.year:
                return int(y)
    return None


def _clean_title_seg(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(s)).strip(" |-–·")


def parse_place(raw: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
    """Free-text place -> (venue, city, country, hybrid). Understands "City, ST", "City, Country", "City & Online"."""
    if not raw:
        return None, None, None, False
    s = re.sub(r"\s+", " ", re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", _html.unescape(raw))).strip(" ,;|·.-–")
    s = re.sub(r"^.*?\b20\d\d\s*[-\u2013\u2014:|]\s*", "", s).strip()         # "PAS 2027 - Minneapolis, Minnesota"
    s = re.sub(r"(?i)^(?:join us|see you|meet us|taking place|held|hosted)\s+(?:in|at)\s+", "", s).strip()
    hybrid = bool(_ONLINE_TAIL_RE.search(s))
    s = _ONLINE_TAIL_RE.sub("", s).strip(" ,;|.-–")
    if not s or re.match(r"^(?:online|virtual)$", s, re.I):
        return None, None, None, False
    if s.isupper() and len(s) > 3:
        s = s.title()
    m = re.match(r"^(.+?),\s*(D\.?C\.?|[A-Z]{2}|[A-Za-z ]+)\.?$", s)
    if m:
        st = m.group(2).strip()
        key = st.upper().replace(".", "") if len(st) <= 4 else st
        if key in _US_STATES or key.replace(".", "") in _US_STATES or st.lower() in _STATE_NAMES:
            city = m.group(1).strip()
            if city.lower() == "washington" and key.replace(".", "") == "DC":
                city = "Washington, D.C."
            return None, city, "United States", hybrid
    v, c, k = split_location(s)
    if k in ("US", "USA", "U.S.", "United States of America"):
        k = "United States"
    return v, c, k, hybrid


# ── edition detection ───────────────────────────────────────────────────────

def _span_ok(d: Dict[str, Any], today: date) -> bool:
    try:
        s, e = date.fromisoformat(d["start"]), date.fromisoformat(d["end"])
    except ValueError:
        return False
    return e >= today and (e - s).days <= 10 and s <= today + timedelta(days=1100)


def find_edition(html: str, lines: List[str], url: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Upcoming edition on an edition/home page: {start,end,date_line,idx,source,year,page_title}. None if absent."""
    today = today or date.today()
    pt = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    page_title = _clean_title_seg(re.sub(r"<[^>]+>", " ", pt.group(1))) if pt else None
    for ev in json_ld_events(html):
        s, e = (ev.get("startDate") or "")[:10], (ev.get("endDate") or ev.get("startDate") or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}$", s) and re.match(r"\d{4}-\d{2}-\d{2}$", e):
            if _span_ok({"start": s, "end": e}, today):
                return {"start": s, "end": e, "date_line": None, "idx": None, "source": "json-ld", "ld": ev,
                        "year": int(s[:4]), "page_title": page_title}
    py = page_year(html, lines, url, today)
    for yr in (None, py):
        for i, ln in enumerate(lines):
            if len(ln) > 220:
                continue
            for seg in _SEP_RE.split(ln):
                if _NOT_EVENT_SEG_RE.search(seg) and not re.search(r"\bfrom\b.{0,30}\bto\b", seg, re.I):
                    continue
                if yr is not None and not re.search(r"\bonline\b|[|·]", ln) and len(ln) > 80:
                    continue
                cand = [d for d in find_dates(norm_dates(seg, yr), today) if _span_ok(d, today)]
                if cand:
                    d = cand[0]
                    occ = [(j, sg) for j, l2 in enumerate(lines) if len(l2) <= 220 for sg in _SEP_RE.split(l2)
                           if any(x["start"] == d["start"] and x["end"] == d["end"] for x in find_dates(norm_dates(sg, yr), today))]
                    occ += [(j, sg) for j, l2 in enumerate(lines) if len(l2) <= 220 and py for sg in _SEP_RE.split(l2)
                            if (j, sg) not in occ and any(x["start"] == d["start"] and x["end"] == d["end"] for x in find_dates(norm_dates(sg, py), today))]
                    return {"start": d["start"], "end": d["end"], "date_line": ln, "idx": i, "source": "header-line",
                            "year": int(d["start"][:4]), "page_title": page_title, "seg": seg, "occ": occ[:6]}
        if py is None:
            break
    return None


def place_candidates(lines: List[str], ed: Dict[str, Any], accept: Optional["re.Pattern[str]"] = None) -> List[str]:
    """Raw place strings near every line carrying the edition's dates, best first."""
    out: List[str] = []
    if ed.get("date_line") is None:
        return out
    for idx, seg in (ed.get("occ") or [(ed.get("idx"), ed.get("seg"))]):
        out += _place_near(lines, ed, idx, seg, accept)
    return out


def _place_near(lines: List[str], ed: Dict[str, Any], idx: Optional[int], seg: Optional[str], accept: Optional["re.Pattern[str]"] = None) -> List[str]:
    out: List[str] = []
    ln = lines[idx] if idx is not None else ed.get("date_line")
    segs = _SEP_RE.split(ln)
    if len(segs) > 1:
        j = segs.index(seg) if seg in segs else 0
        out += [s for s in segs[j + 1:] if not _NOT_EVENT_SEG_RE.search(s)]
        out += [s for s in segs[:j] if len(s.split()) <= 4 and not re.search(r"\d", s) and not _NOT_EVENT_SEG_RE.search(s)]
    m = None
    for cand in (seg or ln,):
        normed = norm_dates(cand, ed.get("year"))
        for dd in find_dates(normed, date(2000, 1, 1)):
            m = (dd["pos"], dd["endpos"])
            break
        if m:
            before, after = normed[:m[0]], normed[m[1]:]
            after = re.sub(r"^[\s,.;:\-–]*(?:in|at|,)?\s*", "", after).strip(" ,.;")
            before = before.strip(" ,.;:-–|·")
            if after and len(after) <= 80 and not _NOT_EVENT_SEG_RE.search(after):
                out.append(after)
            if before and len(before) <= 50 and not re.search(r"\b20\d\d\b|:", before):
                mi = re.search(r"\b(?:in|at)\s+(.+)$", before)
                out.append(mi.group(1) if mi else before)
    if idx is not None:
        for off in (-1, 1, 2, -2):
            k = idx + off
            if 0 <= k < len(lines):
                cand = lines[k]
                core = re.sub(r"^.*?\b20\d\d\s*[-\u2013\u2014:|]\s*", "", cand)           # "PAS 2027 - Minneapolis, Minnesota"
                if accept is not None and accept.search(cand):
                    out.append(cand)
                elif (len(cand) <= 60 and len(core.split()) <= 6 and not re.search(r"\d{3,}|[.!?]$", core)
                        and ("," in core or _VENUE_KW_RE.search(core)) and core[:1].isupper()
                        and not _PLACE_STOP_RE.match(core) and not find_dates(norm_dates(core, ed.get("year")), date(2000, 1, 1))):
                    out.append(cand)
    return [o for o in (re.sub(r"\s+", " ", x).strip() for x in out) if o]


# ── fees ────────────────────────────────────────────────────────────────────

_CUR_MAP = {"€": "EUR", "$": "USD", "£": "GBP", "EUR": "EUR", "USD": "USD", "GBP": "GBP", "CHF": "CHF"}
_AMT_LINE_RE = re.compile(
    r"^(?:(?P<c1>€|\$|£|EUR|USD|GBP|CHF)\s?)?(?P<n>\d{1,3}(?:[.,  ]\d{3})*(?:[.,]\d{2})?|\d+)\s*(?P<c2>€|EUR|USD|GBP|CHF)?\s*\*?$", re.I)
_FREEWORD_RE = re.compile(r"^(?:complimentary|free(?: of charge)?|no charge|included)\*?$", re.I)
_HEAD_MARK_RE = re.compile(r"^(?:category|ticket type|registration (?:category|type)|type|attendee type|delegate type|rate)$", re.I)
_NOT_OPEN_RE = re.compile(
    r"registration[^.]{0,90}(?:will (?:open|be open)|opens?\s+(?:on|in|at)|not yet (?:open|available)|coming soon|to be announced|will be announced|opening soon)"
    r"|(?:fees|rates|prices)[^.]{0,60}(?:will be (?:announced|published|available)|to be announced|tba|tbc)", re.I)


def parse_amount(s: str, default_cur: str) -> Optional[Tuple[float, str]]:
    """Amount-only line ("EUR 800", "$1,395", "€ 1.060", "Complimentary") -> (amount, currency)."""
    s = (s or "").strip()
    if _FREEWORD_RE.match(s):
        return 0.0, default_cur
    m = _AMT_LINE_RE.match(s)
    if not m or not (m.group("c1") or m.group("c2")):
        return None
    cur = _CUR_MAP.get((m.group("c1") or m.group("c2")).upper() if (m.group("c1") or m.group("c2")).isalpha() else (m.group("c1") or m.group("c2")), default_cur)
    raw = m.group("n").replace(" ", "").replace(" ", "")
    if re.match(r"^\d{1,3}(?:[.,]\d{3})+$", raw):
        val = float(re.sub(r"[.,]", "", raw))
    elif re.match(r"^\d+[.,]\d{2}$", raw):
        val = float(raw.replace(",", "."))
    else:
        val = float(re.sub(r"[.,]", "", raw))
    return val, cur


def _is_amt(line: str, cur: str) -> bool:
    return parse_amount(line, cur) is not None


def fee_matrix(lines: List[str], default_currency: str = "EUR", max_tiers: int = 80) -> List[Dict[str, Any]]:
    """Fee grid rendered as text lines: header cells (timeframes), then `label [, description], amount x N` rows."""
    tiers: List[Dict[str, Any]] = []
    n_lines = len(lines)
    i = 0
    headers: List[str] = []
    ncols = 0
    cur_section: Optional[str] = None
    seen = set()
    while i < n_lines:
        if not _is_amt(lines[i], default_currency) or (i > 0 and _is_amt(lines[i - 1], default_currency)):
            i += 1
            continue
        j = i
        while j < n_lines and _is_amt(lines[j], default_currency):
            j += 1
        n = j - i
        if not 2 <= n <= 6:
            i = j
            continue
        # label: nearest previous short non-amount line (skip long description lines)
        label = None
        lab_idx = None
        for k in range(i - 1, max(-1, i - 4), -1):
            if len(lines[k]) <= 70 and not _is_amt(lines[k], default_currency) and not re.match(r"^\(", lines[k]) and not lines[k].endswith((".", ";")):
                label, lab_idx = lines[k], k
                break
        if not label:
            i = j
            continue
        if ncols != n:
            # header cells sit between a header marker (or the previous non-row block) and the first label
            hs: List[str] = []
            section = None
            k = lab_idx - 1
            while (k >= 0 and len(hs) < 12 and not _HEAD_MARK_RE.match(lines[k]) and len(lines[k]) <= 60 and not _is_amt(lines[k], default_currency)
                   and not (len(lines[k]) > 12 and re.search(r"\bfees?\b|registration|tickets?", lines[k], re.I) and not lines[k].startswith("("))):
                hs.insert(0, lines[k])
                k -= 1
            if k >= 1 and _HEAD_MARK_RE.match(lines[k]):
                k -= 1                                  # section heading sits above the "Category" marker
            if k >= 0 and len(lines[k]) <= 80 and re.search(r"fee|registration|ticket|rate|pass|onsite|on-site|digital|pre-day", lines[k], re.I) \
                    and not _is_amt(lines[k], default_currency) and not _HEAD_MARK_RE.match(lines[k]):
                sec = re.sub(r"(?i)\s*\b(?:registration\s+)?(?:fees?|rates?|prices?)\b\s*", " ", lines[k]).strip(" :-\u2013")
                section = sec if sec and sec.lower() != "registration" and not re.search(r"20\d\d", sec) else None
            cells: List[str] = []
            for h in hs:
                if h.startswith("(") and cells:
                    cells[-1] = f"{cells[-1]} {h}"
                else:
                    cells.append(h)
            headers = cells[-n:] if len(cells) >= n else []
            ncols = n
            cur_section = section
        for c, k in enumerate(range(i, j)):
            amt = parse_amount(lines[k], default_currency)
            col = headers[c] if headers and c < len(headers) else None
            deadline = None
            if col and "(" in col:
                paren = col[col.index("("):]
                ds = find_dates(re.sub(r"(?i)\b(?:by|until|before|to)\b", "", paren), date.today())
                if ds and re.search(r"\b(?:by|until|before|to)\b", paren, re.I):
                    deadline = ds[0]["end"]
                col = re.sub(r"\s*\([^)]*\)", "", col).strip() or None
            lab = re.sub(r"\s+\d$", "", re.sub(r"[\*\u2020\u2021]+", "", label)).strip(" ,;")
            parts = [cur_section or "Registration", lab] + ([col] if col else [])
            key = (" \u00b7 ".join(parts), amt[0], amt[1])
            if key in seen:
                continue
            seen.add(key)
            early = bool(col and re.search(r"early|opening|advance|super", col, re.I))
            tiers.append({"tier_label": key[0], "price_gbp": amt[0], "currency": amt[1],
                          "is_early_bird": early, "early_bird_deadline": deadline if early else None})
        i = j
        if len(tiers) >= max_tiers:
            break
    return tiers


def fees_current(lines: List[str], year: int) -> bool:
    """False when the fee page is for another edition or says registration has not opened."""
    text = " ".join(lines)
    if _NOT_OPEN_RE.search(text):
        return False
    first = next((i for i, l in enumerate(lines) if re.search(r"[€$£]\s?\d|\b(?:EUR|USD|GBP)\s?\d", l)), None)
    if first is None:
        return True
    window = " ".join(lines[max(0, first - 25):first + 3])
    if str(year) in window:
        return True
    # no edition year next to the fees: fine only when no other year is there either and the page heading names this edition
    return not re.search(r"(?<!\d)20\d\d(?!\d)", window) and str(year) in " ".join(lines[:15])


# ── key-dates lists ─────────────────────────────────────────────────────────

_KD_HEAD_RE = re.compile(r"^(?:important dates|key dates|deadlines|dates and deadlines|mark your calendars?|timeline\b.*|event|date)$", re.I)
_YEARLESS_KD_RE = re.compile(
    rf"^(?:({_MONTHS_RE})\s+(\d{{1,2}})(?:\s*[-\u2013\u2014]\s*(?:({_MONTHS_RE})\s+)?(\d{{1,2}}))?"
    rf"|(\d{{1,2}})(?:\s*[-\u2013\u2014]\s*(\d{{1,2}}))?\s+({_MONTHS_RE}))$", re.I)


def _mon_num(m: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(m[:3].lower()) + 1


def _before(ref: date, month: int, day: int) -> Optional[date]:
    """The latest month/day on or before `ref` (a yearless milestone date that precedes the congress)."""
    for y in (ref.year, ref.year - 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if d <= ref:
            return d
    return None


def _yearless_span(line: str, ref: Optional[date]) -> Optional[Tuple[date, date]]:
    m = _YEARLESS_KD_RE.match(line.strip())
    if not m or ref is None:
        return None
    if m.group(1):
        m1, d1, m2, d2 = _mon_num(m.group(1)), int(m.group(2)), (_mon_num(m.group(3)) if m.group(3) else _mon_num(m.group(1))), int(m.group(4) or m.group(2))
    else:
        m1 = m2 = _mon_num(m.group(7))
        d1, d2 = int(m.group(5)), int(m.group(6) or m.group(5))
    end = _before(ref, m2, d2)
    start = _before(ref, m1, d1)
    if not end or not start:
        return None
    if start > end:
        start = _before(date(end.year - 1, 12, 31), m1, d1) or start
    return start, end


_TIME_TAIL_RE = re.compile(r"(?i)\b(?:midnight|noon|\d{1,2}[:.]\d{2}(?:\s*[ap]m)?|[ap]m|CES?T|[ECMP][SD]T|UTC|GMT|BST)\b|\([^)]*\)|^(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)[a-z]*,?\s+")


def _date_only(line: str, year_hint: Optional[int], ref: Optional[date] = None) -> Optional[Tuple[date, date]]:
    line = re.sub(r"\s+", " ", _TIME_TAIL_RE.sub(" ", line)).strip(" ,.;")
    if len(line) > 60:
        return None
    ds = find_dates(norm_dates(line, year_hint), date(2000, 1, 1))
    if len(ds) == 1 and (ds[0]["endpos"] - ds[0]["pos"]) >= 0.6 * len(norm_dates(line, year_hint).strip()):
        return date.fromisoformat(ds[0]["start"]), date.fromisoformat(ds[0]["end"])
    return _yearless_span(line, ref)


def key_date_entries(lines: List[str], ref: Optional[date] = None) -> List[Tuple[str, date, date]]:
    """(label, start, end) from a "Key dates" list rendered as alternating label / date lines in either order.
    Orientation: a heading directly before the first date line means date-then-labels, otherwise label-then-date.
    Yearless dates resolve to the latest such date on/before `ref` (the congress start)."""
    idx = [(i, d) for i, l in enumerate(lines) for d in [_date_only(l, None, ref)] if d]
    if len(idx) < 3 and not any(":" in l and len(l) <= 150 and _date_only(l.partition(":")[2].strip(), None, ref) for l in lines):
        return []
    if not idx:
        idx = []
    first = idx[0][0] if idx else 0
    forward = first > 0 and bool(_KD_HEAD_RE.match(lines[first - 1].strip(": ")))
    out: List[Tuple[str, date, date]] = []
    for ln in lines:                                   # "General Abstract Submission Cycle: August 27, 2026 - October 1, 2026"
        if ":" in ln and len(ln) <= 150:
            lab, _, rest = ln.partition(":")
            sp = _date_only(rest.strip(), None, ref)
            if sp and lab.strip():
                out.append((lab.strip(), sp[0], sp[1]))
    for n, (i, (s, e)) in enumerate(idx):
        if forward:
            stop = idx[n + 1][0] if n + 1 < len(idx) else len(lines)
            labels = [l for l in lines[i + 1:min(stop, i + 5)] if len(l) <= 160 and not l.startswith("(") and not re.match(r"(?i)^(?:note|\*)", l)][:2]
        else:
            labels = [lines[i - 1]] if i > 0 and len(lines[i - 1]) <= 90 else []
        for lab in labels:
            if _date_only(lab, None, ref):
                continue
            out.append((lab, s, e))
    return out


# ── extractor ───────────────────────────────────────────────────────────────

_REG_LINK_RE = re.compile(r"regist|\bfees?\b|\brates?\b|pricing|tickets?|passes", re.I)
_REG_LINK_BAD_RE = re.compile(
    r"interest|alert|login|log in|sign in|faq|housing|exhibit|sponsor|group|press|media|visa|invitation|accommodation|hotel|travel|"
    r"stand|partner|volunteer|policy|terms|cancel|substitut|onsite-reg|on-site|sign[\s-]?up|newsletter", re.I)
_ABS_LINK_RE = re.compile(r"abstract|call[\s-]for|submission|submit|key[\s-]dates|important[\s-]dates|deadlines?", re.I)
_ABS_LINK_BAD_RE = re.compile(r"archive|past|previous|award|winner|topic|tips|why-submit|volunteer|workshop|ancillary|scholarly|copyright|categor|page_id=|language", re.I)
_VENUE_LINK_RE = re.compile(r"\bvenue\b", re.I)
_LABEL_VENUE_RE = re.compile(r"^(?:venue|location|where)\s*:\s*(.+)$", re.I)


def _host_root(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    parts = h.split(".")
    return ".".join(parts[-3:] if len(parts) >= 3 and parts[-2] in ("co", "org", "ac", "com", "gov") else parts[-2:])


def anchors(html: str, base: str) -> List[Tuple[str, str]]:
    out = []
    for m in re.finditer(r"(?is)<a\b[^>]*?href\s*=\s*[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", html or ""):
        href = _html.unescape(m.group(1)).strip()
        if _SOCIAL_RE.search(href) or re.search(r"\.(?:png|jpe?g|gif|svg|webp|css|js|ics|zip)(?:\?|$)", href, re.I):
            continue
        text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((text, urljoin(base, href)))
    return out


class SingleCongressExtractor(BaseExtractor):
    HOME_URL: str = ""
    FREE_PATTERN: Optional["re.Pattern[str]"] = None       # edition page text that means attendance is free ("free-to-attend") -> one 0 tier
    ACCEPT_PLACE_RE: Optional["re.Pattern[str]"] = None   # adjacent-to-date lines that are a place even without a comma ("Excel London")
    SOCIETY: str = ""
    EVENT_NAME: str = ""                         # "ESPID" -> title "ESPID 2027"
    DEFAULT_SPECIALTY: Optional[str] = None
    DEFAULT_CURRENCY: str = "EUR"
    EDITION_URLS: Tuple[str, ...] = ()           # extra pages tried (in order) when HOME_URL shows no upcoming edition
    FOLLOW_YEAR_LINKS: bool = True               # homepage shows a past edition: follow "<Event> 2027" links
    REG_URLS: Tuple[str, ...] = ()               # explicit fee pages (else discovered from the edition page nav)
    ABSTRACT_URLS: Tuple[str, ...] = ()
    VENUE_URLS: Tuple[str, ...] = ()
    MAX_AUX_PAGES: int = 3
    REQUEST_GAP_S: float = 0.8

    # ---- hooks ------------------------------------------------------------
    def edition_title(self, ed: Dict[str, Any]) -> str:
        return f"{self.EVENT_NAME} {ed['year']}".strip()

    def parse_place(self, raw: str) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
        return parse_place(raw)

    def venue_from_lines(self, lines: List[str]) -> Optional[str]:
        """Optional per-site hook: venue name from a site's venue page (default none)."""
        return None

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        return self.generic_fees(pages, year)

    # ---- fetch ------------------------------------------------------------
    def _get(self, url: str, tries: int = 3) -> Optional[str]:
        for attempt in range(tries):
            body = fetch_html(url, browser=getattr(self, "browser", None))
            if body and len(body) > 500:
                return body
            logger.warning(f"{self.SOCIETY}: fetch attempt {attempt + 1}/{tries} failed for {url}")
            time.sleep(1.5 * (attempt + 1))
        return None

    def _edition_from(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        lines = html_lines(html)
        ed = find_edition(html, lines, url)
        if ed:
            ed.update(url=url, lines=lines)
        return ed

    # ---- listing ----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        home = self._get(self.HOME_URL)
        tried = [self.HOME_URL]
        ed = self._edition_from(self.HOME_URL, home) if home else None
        today = date.today()
        if not ed:
            cands: List[str] = list(self.EDITION_URLS)
            if self.FOLLOW_YEAR_LINKS and home:
                yl: List[Tuple[int, str]] = []
                kd: List[str] = []
                for text, href in anchors(home, self.HOME_URL):
                    ys = [int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", text)]
                    h0 = href.split("#")[0]
                    if h0 == self.HOME_URL or h0 in cands:
                        continue
                    if ys and max(ys) >= today.year:
                        yl.append((-max(ys), h0))
                    elif re.search(r"key[\s-]?dates|important[\s-]?dates", f"{text} {urlparse(h0).path}", re.I):
                        kd.append(h0)
                for _, h0 in sorted(yl, key=lambda t: t[0]):          # latest year first
                    if h0 not in cands:
                        cands.append(h0)
                cands += [k for k in kd if k not in cands]
            for url in cands[:4]:
                if url in tried:
                    continue
                tried.append(url)
                time.sleep(self.REQUEST_GAP_S)
                body = self._get(url)
                ed = self._edition_from(url, body) if body else None
                if ed:
                    home = body
                    break
        if not ed:
            logger.info(f"{self.SOCIETY}: no upcoming edition announced on {tried}")
            return []
        ev = ed.get("ld")
        shell: Dict[str, Any] = {
            "title": self.edition_title(ed), "booking_url": ed["url"], "start_date": ed["start"], "end_date": ed["end"],
            "event_type": "conference", "edition_year": ed["year"],
        }
        if ev:
            v, c, k, virt = location_from_ld(ev)
            if v or c:
                shell["venue_raw"] = ", ".join(x for x in (v, c, k) if x)
        logger.info(f"{self.SOCIETY}: edition {shell['title']} {ed['start']}..{ed['end']} via {ed['source']} at {ed['url']}")
        return [shell]

    # ---- discovery of secondary pages ------------------------------------
    def _discover(self, html: str, base: str, want_re: "re.Pattern[str]", bad_re: Optional["re.Pattern[str]"]) -> List[str]:
        out: List[str] = []
        root = _host_root(base)
        for text, href in anchors(html, base):
            blob = f"{text} {urlparse(href).path}"
            if not want_re.search(blob) or (bad_re and bad_re.search(blob)):
                continue
            if _host_root(href) != root or href.split("#")[0].rstrip("/") == base.rstrip("/"):
                continue
            h = href.split("#")[0]
            if h not in out:
                out.append(h)
        return out

    def _fetch_aux(self, urls: List[str], base_html: str, base_url: str, cap: int) -> Dict[str, str]:
        pages: Dict[str, str] = {}
        for u in urls[:cap]:
            time.sleep(self.REQUEST_GAP_S)
            body = self._get(u, tries=2) if u != base_url else base_html
            if body:
                pages[u] = body
        return pages

    # ---- fees -------------------------------------------------------------
    def generic_fees(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        for url, html in pages.items():
            lines = html_lines(html)
            if not fees_current(lines, year):
                continue
            for ev in json_ld_events(html):
                t = tiers_from_offers(ev, self.DEFAULT_CURRENCY)
                if t:
                    return t
            tiers = fee_matrix(lines, self.DEFAULT_CURRENCY)
            if tiers:
                return tiers
            body = _DETAIL_CHROME_RE.sub(" ", html)
            tiers = parse_pricing_tables(body, default_currency=self.DEFAULT_CURRENCY)
            if tiers:
                return tiers
        return []

    # ---- detail -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or self.HOME_URL
        html = page.content() if page is not None else ""
        if not html or len(html) < 500:
            html = self._get(url) or ""
        return self.detail_from_html(html, url, shell, llm_call)

    def detail_from_html(self, html: str, url: str, shell: Dict[str, Any], llm_call: Optional[Callable[[str], Optional[str]]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": self.SOCIETY, "event_type": "conference"}
        lines = html_lines(html)
        title = shell.get("title") or self.EVENT_NAME
        year = int(shell.get("edition_year") or (shell.get("start_date") or "0000")[:4])
        ed = find_edition(html, lines, url) or {}
        out["start_date"], out["end_date"] = shell.get("start_date"), shell.get("end_date") or shell.get("start_date")

        # place + format
        venue = city = country = None
        hybrid = False
        raws: List[str] = []
        if shell.get("venue_raw"):
            raws.append(shell["venue_raw"])
        meta_lines = [x for x in (_meta(html, "og:description"), _meta(html, "description"), _meta(html, "og:title")) if x]
        ed2 = find_edition(html, lines + meta_lines, url) or ed
        raws += place_candidates(lines + meta_lines, ed2, self.ACCEPT_PLACE_RE) if ed2.get("date_line") else []
        for raw in raws:
            v, c, k, h = self.parse_place(raw)
            hybrid = hybrid or h
            if v or c:
                venue, city, country = venue or v, city or c, country or k
                break
        # venue name: the site's own venue page / nav link (only when the date line gave none)
        vraws: List[str] = []
        if not venue:
            venue_pages = self._fetch_aux(list(self.VENUE_URLS) or self._discover(html, url, _VENUE_LINK_RE, None)[:1], html, url, 1)
            for vh in venue_pages.values():
                vl = html_lines(vh)
                for n_, ln in enumerate(vl):
                    m = _LABEL_VENUE_RE.match(ln)
                    if m:
                        vraws.append(m.group(1))
                        break
                    if re.match(r"(?i)^(?:the )?venue$", ln):
                        nxt = next((x for x in vl[n_ + 1:n_ + 4] if not x.endswith(":") and len(x) <= 60 and not re.search(r"[.!?]$", x)), None)
                        if nxt:
                            vraws.append(nxt)
                            break
                else:
                    hv = self.venue_from_lines(vl)
                    if hv:
                        vraws.append(hv)
            for raw in vraws:
                v, c, k, h = self.parse_place(raw)
                v = v or (raw.strip() if c and not k and "," not in raw else None)    # a bare name on the venue page IS the venue
                if v:
                    venue = v
                    city, country = (city or c) if v != raw.strip() else city, country or k
                    break
            if not venue:
                for text, _href in anchors(html, url):         # nav link "The Venue EFORT 2027 at MEGARON"
                    m = re.search(r"\bvenue\b.*?\bat\s+([A-Z][\w &'\u2019-]{2,40})$", text)
                    if m:
                        venue = m.group(1).strip()
                        break
        if venue and not city:                     # "Liverpool Experience Campus": city = a venue prefix the page also shows on its own line
            words = venue.split()
            for n in (2, 1):
                pre = " ".join(words[:n])
                if len(words) > n and pre[:1].isupper() and any(l == pre for l in lines):
                    city = pre
                    break
        head = " ".join(lines[:60])
        if re.search(r"&\s*online|\+\s*online|hybrid|onsite\s*(?:&|and)\s*online|in[\s-]person\s*(?:&|and)\s*(?:online|virtual)", " ".join(raws) + " " + head[:1500], re.I):
            hybrid = True
        if venue and not city:                     # venue has no city: a "<City>, <Country>" line naming a word of the venue
            vwords = set(re.findall(r"[A-Z][\w'\u2019-]+", venue))
            for ln in lines[:120]:
                for m in re.finditer(r"\b([A-Z][\w'\u2019-]+(?: [A-Z][\w'\u2019-]+)?),\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b", ln):
                    if m.group(1) in vwords and m.group(2) in _COUNTRIES:
                        city, country = m.group(1), country or m.group(2)
                        break
                if city:
                    break
        venue = clip_venue(venue)
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        if country:
            out["region"] = country
        if venue or city:
            out["event_format"] = "hybrid" if hybrid else "in_person"

        # description + specialty
        other_year = re.compile(r"(?<!\d)(?!%d)20\d\d(?!\d)" % year)
        body_lines = [l for l in lines[8:] if not re.search(r"cookie|consent|privacy|storage or access", l, re.I) and not other_year.search(l)
                      and not re.match(r"(?i)^(?:thank you|thanks|we hope you|see you|missed|watch|revisit)", l)]
        desc = pick_description(body_lines, title)
        if not desc:
            md = _meta(html, "og:description") or _meta(html, "description")
            desc = md if md and len(md) >= 50 and not re.search(r"cookie|consent", md, re.I) else None
        desc = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", desc or ""))).strip()[:600]
        if desc:
            out["description"] = desc
        spec = self.DEFAULT_SPECIALTY or classify_specialty(title) or classify_specialty(title, out.get("description"))
        if not spec and llm_call:
            try:
                resp = (llm_call("Name the single medical specialty (1-3 words) this congress is for. Reply with only the "
                                 f"specialty or NONE.\nTitle: {title}\nText: {' '.join(lines[:40])[:1200]}") or "").strip().strip(".\"'")
                if resp and resp.upper() != "NONE" and len(resp) <= 40:
                    spec = resp
            except Exception:  # noqa: BLE001
                spec = None
        if spec:
            out["specialty"] = spec

        # CPD (explicit "N CME credits" only)
        m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:AMA PRA Category 1 Credits?|CME|CPD|EACCME)\s*(?:credits?|points?|hours?)", " ".join(l for l in lines if not other_year.search(l)), re.I)
        if m and 0.5 <= float(m.group(1)) <= 100:
            out["cpd_points"] = float(m.group(1))
            out["cpd_accredited"] = True

        # fees: ONE hop to the site's own registration page(s)
        reg_urls = list(self.REG_URLS) or self._discover(html, url, _REG_LINK_RE, _REG_LINK_BAD_RE)
        reg_pages = self._fetch_aux(([url] if not reg_urls else []) + reg_urls, html, url, self.MAX_AUX_PAGES)
        if url not in reg_pages and html:
            reg_pages[url] = html
        tiers = self.fees_from_pages(reg_pages, year)
        if not tiers and self.FREE_PATTERN and self.FREE_PATTERN.search(" ".join(lines)):
            tiers = [{"tier_label": "Attendance \u00b7 Free to attend", "price_gbp": 0.0, "currency": self.DEFAULT_CURRENCY,
                      "is_early_bird": False, "early_bird_deadline": None}]
        if tiers:
            out["pricing_tiers"] = tiers

        # abstracts / key dates
        abs_urls = list(self.ABSTRACT_URLS) or sorted(
            self._discover(html, url, _ABS_LINK_RE, _ABS_LINK_BAD_RE),
            key=lambda u: -(3 if re.search(r"deadline|important|key[\s-]?dates", u, re.I) else 2 if re.search(r"submi|call", u, re.I) else 1))
        abs_pages = self._fetch_aux(abs_urls, html, url, self.MAX_AUX_PAGES)
        abs_pages.setdefault(url, html)
        self.apply_abstracts(out, abs_pages, shell)
        return out

    def apply_abstracts(self, out: Dict[str, Any], pages: Dict[str, str], shell: Dict[str, Any]) -> None:
        today = date.today()
        try:
            start = date.fromisoformat(shell["start_date"])
        except (KeyError, ValueError, TypeError):
            start = None
        best: Optional[Tuple[bool, Optional[date], Optional[str]]] = None
        kd = [e for html in pages.values() for e in key_date_entries(html_lines(html), start)
              if re.search(r"abstract|call for papers|poster", e[0], re.I)
              and re.search(r"clos|deadline|due|call for|submission", e[0], re.I)
              and not re.search(r"notif|accepted|programme|program guide", e[0], re.I)
              and not (e[1] == e[2] and re.search(r"\bopens?\b", e[0], re.I) and not re.search(r"clos", e[0], re.I))]
        if kd:
            fut = sorted(e[2] for e in kd if e[2] >= today)
            dl = fut[0] if fut else max(e[2] for e in kd)
            out["abstract_open"] = dl >= today
            out["abstract_deadline"] = dl.isoformat()
            return
        for html in pages.values():
            text = " ".join(html_lines(html))
            if str(shell.get("edition_year") or "") and not self._mentions_edition(text, shell):
                continue
            op, dl, note = classify_submission(text, today, start)
            if dl and (best is None or best[1] is None or (dl >= today and (best[1] < today or dl < best[1]))):
                best = (op, dl, note)
            elif best is None and (op or note):
                best = (op, dl, note)
        if best:
            op, dl, note = best
            if dl and start and dl >= start:                 # a "deadline" on/after the congress itself is a misparse
                return
            out["abstract_open"] = bool(op)
            if dl:
                out["abstract_deadline"] = dl.isoformat()
            elif note:
                out["abstract_deadline_note"] = note

    @staticmethod
    def _mentions_edition(text: str, shell: Dict[str, Any]) -> bool:
        y = str(shell.get("edition_year"))
        py = str(int(y) - 1) if y.isdigit() else ""
        # a page that only talks about the previous edition's call for abstracts is not this edition's
        return y in text or not py or py not in text
