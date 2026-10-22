"""SIU (Societe Internationale d'Urologie): events page + the annual Congress.

`siu-urology.org/events` is one server-rendered page of blocks, each opened by `<a name="eventNN"></a>`, then
`<h3>title</h3>`, a free-text date line ("November 20-21, 2026", "February 12,2026", "August 31-November 21" with no
year, "April 30 2026" for posts), a location line ("Wuhan, China", "Online", "Remote", "Various") and free HTML. There
are about five blocks; most are past or undated hubs, so only a handful survive the date filter. Year-less ranges take
the year from the page footer ("Copyright 2026") and are dropped once they have ended. Each block becomes a shell whose
`booking_url` is the events page plus `#eventNN`, and its description is cut from the block text in the listing phase.

The flagship Congress is not on that page. The events page links `/congress-YYYY/...`; the newest year's `/highlights`
page says "will take place in Florence, Italy, from November 11-14, 2026" and "The 46th SIU Congress". Its venue is on
`/general-information` ("Official Venue ...") and its public fees on `/registration` (tables of IN PERSON / VIRTUAL
ONLY rows, EARLY and REGULAR columns, member and non-member sections, euros, plus a Bench-to-Bedside-only table).
Early columns whose deadline has passed are dropped. "Free with SIU Membership" rows carry no price and are skipped.
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

_ROOT = "https://www.siu-urology.org"
_EVENTS_URL = _ROOT + "/events"
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag or ""))).replace("\xa0", " ").strip()


def _mon(s: str) -> Optional[int]:
    return _MON.get((s or "")[:3].lower())


def parse_date_line(text: str, default_year: Optional[int] = None) -> Optional[Tuple[str, str]]:
    """"November 20-21, 2026" / "February 12,2026" / "August 31-November 21" -> (start, end) ISO (pure).
    A line without a year uses `default_year`; with neither it returns None."""
    t = _txt(text).replace("–", "-").replace("—", "-")
    try:
        m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\s*-\s*(\d{1,2})\s*,?\s*(\d{4})", t)
        if m and _mon(m.group(1)):
            y, mo = int(m.group(4)), _mon(m.group(1))
            return date(y, mo, int(m.group(2))).isoformat(), date(y, mo, int(m.group(3))).isoformat()
        m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\s*-\s*([A-Za-z]{3,9})\s+(\d{1,2})\s*,?\s*(\d{4})?", t)
        if m and _mon(m.group(1)) and _mon(m.group(3)):
            y2 = int(m.group(5)) if m.group(5) else default_year
            if not y2:
                return None
            y1 = y2 - 1 if _mon(m.group(1)) > _mon(m.group(3)) else y2
            return date(y1, _mon(m.group(1)), int(m.group(2))).isoformat(), date(y2, _mon(m.group(3)), int(m.group(4))).isoformat()
        m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\s*,?\s*(\d{4})", t)
        if m and _mon(m.group(1)):
            d = date(int(m.group(3)), _mon(m.group(1)), int(m.group(2))).isoformat()
            return d, d
    except ValueError:
        return None
    return None


def parse_events_page(html: str) -> List[Dict[str, Any]]:
    """Events page -> one dict per `<a name="eventNN">` block (pure)."""
    page_year = None
    cp = re.search(r"Copyright\s+(\d{4})", html or "")
    if cp:
        page_year = int(cp.group(1))
    body = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>", " ", html or "")
    parts = re.split(r'<a name="event(\d+)"></a>', body)
    out: List[Dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        blk = parts[i + 1]
        h = re.search(r"(?is)<h3>(.*?)</h3>\s*(.*?)<br\s*/?>\s*([^<\r\n]*)", blk)
        if not h:
            continue
        dates = parse_date_line(h.group(2), page_year)
        place = _txt(h.group(3))
        rest = blk[h.end():]
        prose = [p for p in (_txt(x) for x in re.findall(r"(?is)<p[^>]*>(.*?)</p>", rest)) if len(p) > 60 and "Follow Us" not in p and "Copyright" not in p]
        out.append({"id": parts[i], "title": _txt(h.group(1)), "start_date": dates[0] if dates else None,
                    "end_date": dates[1] if dates else None, "place": place, "description": prose[0][:600] if prose else None})
    return out


def split_place(raw: str) -> Dict[str, Any]:
    """"Wuhan, China" -> city/region; Online/Remote -> online; Various/blank -> nothing."""
    raw = (raw or "").strip()
    if re.fullmatch(r"(?i)online|remote|virtual|webinar", raw):
        return {"event_format": "online"}
    if not raw or re.fullmatch(r"(?i)various|tbc|tba|tbd", raw):
        return {}
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: Dict[str, Any] = {"city": parts[0], "event_format": "in_person"}
    if len(parts) >= 2:
        out["region"] = parts[-1]
    return out


def congress_info(html: str) -> Optional[Dict[str, Any]]:
    """/congress-YYYY/highlights -> {start_date, end_date, city, region, edition} (pure)."""
    t = _txt(re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>", " ", html or ""))
    m = re.search(r"will take place in ([A-Z][A-Za-z .'-]+?),\s*([A-Z][A-Za-z .'-]+?),\s*from\s+(.{5,40}?\d{4})", t)
    if not m:
        return None
    dates = parse_date_line(m.group(3))
    if not dates:
        return None
    ed = re.search(r"The\s+(\d+(?:st|nd|rd|th))\s+SIU Congress", t)
    intro = re.search(r"The Soci\S+ Internationale d\S+Urologie \(SIU\) is pleased.*?\.\s+The \d+\w+ SIU Congress.*?\.", t)
    return {"intro": intro.group(0)[:500] if intro else None, "start_date": dates[0], "end_date": dates[1], "city": m.group(1).strip(), "region": m.group(2).strip(),
            "edition": ed.group(1) if ed else None}


def _amount(raw: str) -> Optional[float]:
    raw = re.sub(r"[€\s]", "", raw or "").strip(".,")
    m = re.fullmatch(r"(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?", raw)
    if not m:
        return None
    return float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))


def parse_registration(html: str, congress_year: int) -> List[Dict[str, Any]]:
    """/registration -> tiers (pure). Section = In person | Virtual | Bench-to-Bedside only; category carries member status."""
    today = date.today().isoformat()
    tiers: List[Dict[str, Any]] = []
    for m in re.finditer(r"(?is)<table\b[^>]*>.*?</table>", html or ""):
        before = html[max(0, m.start() - 600):m.start()]
        status = None
        for h in re.finditer(r"(?i)(Non-Member|SIU Member|Bench-to-Bedside Only)\s+Registration Fees", _txt(before)):
            status = h.group(1).lower()
        if not status:
            continue
        rows = [[_txt(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)] for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(0))]
        if not rows:
            continue
        head = rows[0]
        cols: List[Tuple[str, bool]] = []                           # (timeframe label, still open)
        for c in head[1:]:
            early = bool(re.match(r"(?i)\s*early", c))
            dl = re.search(r"(?i)deadline\s+([A-Za-z]{3,9})\s+(\d{1,2})", c)
            open_ = True
            if early and dl and _mon(dl.group(1)):
                try:
                    open_ = date(congress_year, _mon(dl.group(1)), int(dl.group(2))).isoformat() >= today
                except ValueError:
                    pass
            cols.append(("Early" if early else "Regular", open_))
        mode = None
        for r in rows[1:]:
            if len(r) == 1:
                mm = re.match(r"(?i)\s*(in person|virtual only|virtual)", r[0])
                if mm:
                    mode = "In person" if mm.group(1).lower() == "in person" else "Virtual"
                continue
            label = re.sub(r"[*‡†\s]+$", "", re.sub(r"\s*[*‡†]+\s*", " ", r[0])).strip()
            if not label:
                continue
            section = "Bench-to-Bedside only" if status.startswith("bench") else (mode or "In person")
            if status.startswith("siu member"):
                cat = re.sub(r"(?i)^SIU Member:\s*", "", label)
                cat = f"Member: {cat}" if not re.match(r"(?i)^member", label) else cat
            elif status.startswith("non-member"):
                cat = re.sub(r"(?i)^non-member", "Non-member", label) if re.match(r"(?i)^non-member", label) else f"Non-member: {label}"
            else:
                cat = label
            for (timeframe, open_), cell in zip(cols, r[1:]):
                price = _amount(cell) if re.search(r"\d", cell) else None
                if price is None or not open_:
                    continue
                tiers.append({"tier_label": " · ".join((section, cat, timeframe + " · excl. 22% VAT"))[:120], "price_gbp": price, "currency": "EUR",
                              "is_early_bird": timeframe == "Early", "early_bird_deadline": None})
    seen, out = set(), []
    for t in tiers:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


class SiuUrologyExtractor(BaseExtractor):
    SOCIETY = "SIU"
    DEFAULT_SPECIALTY = "Urology"
    REQUEST_GAP_S = 1.0

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(_EVENTS_URL, browser=getattr(self, "browser", None))
        if not html or "eventsgrid" not in html:
            if not html:                      # 2026-10-22: the whole site answered HTTP 500 with an empty body (origin outage)
                from extractors import http_fetch
                http_fetch.note_unreachable(_EVENTS_URL, ConnectionError("net::ERR_FAILED (site outage: no usable response)"),
                                            getattr(self, "browser", None))
            return None
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for e in parse_events_page(html):
            if not e["start_date"]:
                logger.info(f"SIU: skipping undated block {e['title']!r}")
                continue
            if e["end_date"] < today:
                continue
            if e["start_date"] < today and (date.fromisoformat(e["end_date"]) - date.fromisoformat(e["start_date"])).days > 7:
                logger.info(f"SIU: skipping in-progress programme {e['title']!r} (started {e['start_date']}, enrolment closed)")
                continue
            if re.fullmatch(r"(?i)various", e["place"] or "") and e["start_date"] == e["end_date"]:
                logger.info(f"SIU: skipping hub post {e['title']!r}")
                continue
            url = f"{_EVENTS_URL}#event{e['id']}"
            shells.append({"title": e["title"], "booking_url": url, "source_url": url, "start_date": e["start_date"], "end_date": e["end_date"],
                           "venue_raw": e["place"], "category": None, "blurb": e["description"]})
        years = sorted({int(y) for y in re.findall(r"/congress-(\d{4})/", html)}, reverse=True)
        if not years:                                   # discovery fallback: the congress pages follow /congress-<year>/
            years = [date.today().year]
        if years:
            time.sleep(self.REQUEST_GAP_S)
            hi = f"{_ROOT}/congress-{years[0]}/highlights"
            info = congress_info(fetch_html(hi, browser=getattr(self, "browser", None)) or "")
            if info and info["end_date"] >= today:
                title = f"SIU {years[0]} Congress" + (f" ({info['edition']})" if info["edition"] else "")
                shells.append({"title": title, "booking_url": hi, "source_url": hi, "start_date": info["start_date"], "end_date": info["end_date"],
                               "venue_raw": f"{info['city']}, {info['region']}", "category": "Congress", "blurb": info["intro"],
                               "congress_year": years[0]})
            else:
                logger.warning(f"SIU: congress-{years[0]} highlights gave no upcoming dates")
        logger.info(f"SIU: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": self.SOCIETY, "specialty": self.DEFAULT_SPECIALTY, "start_date": shell.get("start_date"),
                               "end_date": shell.get("end_date")}
        out.update(split_place(shell.get("venue_raw") or ""))
        title = shell.get("title") or ""
        if shell.get("blurb"):
            out["description"] = shell["blurb"]
        year = shell.get("congress_year")
        if not year:
            out["event_type"] = "course" if re.search(r"(?i)\bprogramme\b|\bacademy\b|urotrainer", title) else \
                ("workshop" if re.search(r"(?i)grand round|webinar|workshop", title) else "conference")
            return out
        # ---- the Congress: venue + fees from sibling pages
        out["event_type"] = "conference"
        out["is_flagship"] = True
        base = f"{_ROOT}/congress-{year}"
        time.sleep(self.REQUEST_GAP_S)
        gi = fetch_html(f"{base}/general-information", browser=getattr(self, "browser", None)) or ""
        v = re.search(r"(?is)Official Venue\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<–]{3,80})", gi)
        if v:
            out["venue_name"] = re.split(r"\s+[\u2013\u2014-]\s+|,", _txt(v.group(1)))[0].strip(" ,-") or None
        time.sleep(self.REQUEST_GAP_S)
        reg = fetch_html(f"{base}/registration", browser=getattr(self, "browser", None)) or ""
        tiers = parse_registration(reg, year)
        if tiers:
            out["pricing_tiers"] = tiers
        return out
