# extractors/sccm.py
"""
SCCM (Society of Critical Care Medicine) — conference calendar extractor.

Listing: https://sccm.org/education-center/conference-calendar is ONE server-
rendered page holding every calendar entry (~75 cards in
`div.filterData.list-item`; the filter UI is client-side jplist, there is no
pagination and no stated total). Each card carries date(s), optional time,
location or venue, type/category tags, title and a short description.

Quirks that drive the design:
  * Every card links OUT to a third-party page (hospital sites, Cvent, Zoom,
    eventscribe, Facebook ...). Many hosts repeat across dates (geisinger.edu,
    the Honolulu FCCS page ...), so the card href is NOT a usable unique
    source_url, and several hosts are bot-walled. Each shell therefore gets a
    stable identity URL `<listing>#evt-<hash>` (the browser just reloads the
    listing; the fragment is ignored by the server) and extract_detail() returns
    the real destination as booking_url / organiser_url.
  * The flagship Critical Care Congress is NOT a calendar card (only its
    pre-Congress courses are). It is added from its own page
    /annual-congress/critical-care-conference.
  * Card types -> event_type: Hosted Training -> course, SCCM Congress (pre-
    Congress sessions) -> workshop, Webcast -> workshop (online), Non-SCCM
    Event -> conference.
  * No fees anywhere on the listing, and the Congress registration page lives on
    eventscribe (Cloudflare 403), so pricing_tiers is [] throughout.
  * www.sccm.org does not resolve everywhere; use the bare host sccm.org.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger

HOST = "https://sccm.org"
LISTING_URL = f"{HOST}/education-center/conference-calendar"
CONGRESS_URL = f"{HOST}/annual-congress/critical-care-conference"
DEFAULT_SPECIALTY = "Intensive Care Medicine"

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}

_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _txt(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment or "")
    s = re.sub(r"(?i)<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(html_lib.unescape(s).replace("\xa0", " ").split())


def _mdy(s: str) -> Optional[str]:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(20\d{2})\s*", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _start_time(text: str) -> Optional[str]:
    """'6:30 a.m. – 5:30 p.m. Pacific Time' -> '06:30' (start of the range)."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", text or "", re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3).lower() == "p":
        h += 12
    return f"{h:02d}:{int(m.group(2) or 0):02d}"


def _split_location(loc: str) -> Dict[str, Optional[str]]:
    """'Danville, PA' -> city Danville / region 'Pennsylvania, USA';
    'Rome, Italy' -> Rome / Italy; 'Toluca, Estado de Mexico, Mexico' ->
    Toluca / 'Estado de Mexico, Mexico'."""
    parts = [p.strip() for p in (loc or "").split(",") if p.strip()]
    if not parts:
        return {"city": None, "region": None}
    city = parts[0]
    if len(parts) == 1:
        return {"city": city, "region": None}
    if len(parts) == 2 and parts[1].upper() in _US_STATES:
        return {"city": city, "region": f"{_US_STATES[parts[1].upper()]}, USA"}
    return {"city": city, "region": ", ".join(parts[1:])}


def _identity(title: str, start: str, end: str, time_txt: str, loc: str, cat: str) -> str:
    key = "|".join([title.lower(), start or "", end or "", time_txt or "", loc.lower(), cat.lower()])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _abs(href: str) -> str:
    href = html_lib.unescape((href or "").strip())
    if href.startswith("/"):
        return HOST + href
    # www.sccm.org does not resolve everywhere; the bare host serves the same pages.
    return re.sub(r"^https?://www\.sccm\.org", HOST, href, flags=re.I)


def _event_type(types: List[str]) -> str:
    t = " ".join(types).lower()
    if "hosted training" in t:
        return "course"
    if "webcast" in t or "congress" in t:
        return "workshop"
    return "conference"


# --------------------------------------------------------------------------- #
# Listing parser
# --------------------------------------------------------------------------- #
def parse_cards(page_html: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Parse every calendar card on the listing page. Pure function."""
    today_iso = (today or date.today()).isoformat()
    out: List[Dict[str, Any]] = []
    seen = set()
    chunks = re.split(r"""<div class=['"]filterData list-item['"]>""", page_html)[1:]
    for chunk in chunks:
        # A card ends at its <hr>; keep the tail of the final chunk from bleeding in.
        card = re.split(r"""<hr class=['"]my-0""", chunk, maxsplit=1)[0]
        m_href = re.search(r'<a\s+href="([^"]*)"', card)
        m_h3 = re.search(r"(?is)<h3[^>]*>(.*?)</h3>", card)
        m_h4 = re.search(r"(?is)<h4[^>]*>(.*?)</h4>", card)
        if not (m_h3 and m_h4):
            continue
        title = _txt(m_h3.group(1))
        dates = re.findall(r"\d{1,2}/\d{1,2}/20\d{2}", _txt(m_h4.group(1)))
        start = _mdy(dates[0]) if dates else None
        end = _mdy(dates[-1]) if dates else None
        if not title or not start:
            continue
        if (end or start) < today_iso:
            continue
        if re.search(r"\b(cancel+ed|postponed)\b", title, re.I):
            continue

        time_txt, loc = "", ""
        for kind, val in re.findall(
            r"(?is)<dt>\s*<i[^>]*aria-label=['\"](time|location)['\"][^>]*>\s*</i>\s*</dt>\s*<dd[^>]*>(.*?)</dd>", card
        ):
            if kind == "time":
                time_txt = _txt(val)
            else:
                loc = _txt(val)
        types = [_txt(t) for t in re.findall(r"""(?is)<span class=['"]tag type['"]>(.*?)</span>""", card)]
        cats = [_txt(t) for t in re.findall(r"""(?is)<span class=['"]tag category[^'"]*['"]>(.*?)</span>""", card)]
        cats = [c for c in cats if c and c.lower() != "none"]
        # Description = text between </h3> and the "Learn More" button. The raw HTML nests
        # <p> inside <p>, which a browser re-parses differently, so work on flattened text
        # (identical either way) and drop the trailing host contact details (personal data).
        seg = card[m_h3.end():]
        seg = re.split(r"""(?i)<p>\s*<span class=['"]btn""", seg, maxsplit=1)[0]
        desc = re.split(r"\s(?:Host|Phone|E-Mail):", " " + _txt(seg), maxsplit=1)[0].strip()

        ident = _identity(title, start, end or start, time_txt, loc, "/".join(cats))
        if ident in seen:
            continue
        seen.add(ident)
        out.append({
            "ident": ident, "title": title, "start_date": start, "end_date": end or start,
            "time_txt": time_txt, "location": loc, "types": types, "categories": cats,
            "description": desc, "href": _abs(m_href.group(1)) if m_href else "",
        })
    return out


def parse_congress(page_html: str) -> Optional[Dict[str, Any]]:
    """Dates / venue / description of the flagship Congress from its own page."""
    meta = re.search(r'(?is)<meta\s+name="description"\s+content="([^"]*)"', page_html)
    body = re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1>", " ", page_html)
    lines = [l for l in (" ".join(html_lib.unescape(x).split())
                         for x in re.sub(r"<[^>]+>", "\n", body).split("\n")) if l]
    date_re = re.compile(
        r"^(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),\s*(20\d{2})$")
    for i, line in enumerate(lines):
        m = date_re.match(line)
        # The hero repeats the date; the SECOND occurrence is followed by venue + city.
        if not m:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not re.search(r"center|centre|hotel|hall|convention", nxt, re.I):
            continue
        mon = _MONTHS[m.group(1).lower()]
        y = int(m.group(4))
        loc = lines[i + 2] if i + 2 < len(lines) else ""
        return {
            "start_date": date(y, mon, int(m.group(2))).isoformat(),
            "end_date": date(y, mon, int(m.group(3))).isoformat(),
            "venue": nxt, "location": loc,
            "description": html_lib.unescape(meta.group(1)).strip() if meta else "",
        }
    return None


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #
class SccmExtractor(BaseExtractor):
    """SCCM — one calendar page + the flagship Congress page."""

    # ---- Phase A ---------------------------------------------------------- #
    def _fetch(self, url: str) -> Optional[str]:
        for attempt in range(3):
            body = fetch_html(url, browser=getattr(self, "browser", None))
            if body:
                return body
            logger.warning(f"SCCM: fetch of {url} failed (attempt {attempt + 1}/3)")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        listing = self._fetch(LISTING_URL)
        if not listing:
            logger.warning("SCCM: listing page unavailable")
            return []
        cards = parse_cards(listing)
        logger.info(f"SCCM: {len(cards)} upcoming calendar cards")

        shells: List[Dict[str, Any]] = []
        for c in cards:
            loc_l = c["location"].lower()
            online = ("zoom" in loc_l or "virtual" in loc_l or "online" in loc_l
                      or "webcast" in " ".join(c["types"]).lower()
                      or re.search(r"\((virtual|online)\)", c["title"], re.I) is not None)
            # Webcast "location" is a time or 'Zoom' -> never a city.
            has_place = bool(c["location"]) and not online
            shells.append({
                "title": c["title"],
                "booking_url": f"{LISTING_URL}#evt-{c['ident']}",
                "start_date": c["start_date"],
                "start_time": _start_time(c["time_txt"]),
                "location_hint": "Online" if online else (c["location"] or None) if has_place else None,
                "description_hint": c["description"] or None,
                "category": None,
                "_sccm": {
                    "end_date": c["end_date"], "location": c["location"], "online": online,
                    "types": c["types"], "categories": c["categories"], "href": c["href"],
                },
            })

        # Flagship Congress (not a calendar card).
        cong_html = self._fetch(CONGRESS_URL)
        cong = parse_congress(cong_html) if cong_html else None
        if cong and cong["end_date"] >= date.today().isoformat():
            shells.append({
                "title": f"{cong['start_date'][:4]} Critical Care Congress",
                "booking_url": CONGRESS_URL,
                "start_date": cong["start_date"],
                "start_time": None,
                "location_hint": cong["location"] or None,
                "description_hint": cong["description"] or None,
                "category": "conference",
                "_sccm": {"flagship": True, "end_date": cong["end_date"], "venue": cong["venue"],
                          "location": cong["location"], "href": CONGRESS_URL},
            })
        else:
            logger.warning("SCCM: could not parse the flagship Congress page")
        return shells

    # ---- Phase B ---------------------------------------------------------- #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        meta = shell.get("_sccm") or {}
        if meta.get("flagship"):
            return self._flagship(page, shell, meta)
        if not meta:
            # Shell lost its payload (should not happen) — rebuild from the live listing.
            return self._from_listing_page(page, shell, llm_call)
        return self._card_detail(shell, meta, llm_call)

    def _from_listing_page(self, page, shell, llm_call) -> Dict[str, Any]:
        ident = (shell.get("booking_url") or "").rsplit("#evt-", 1)[-1]
        try:
            cards = parse_cards(page.content())
        except Exception:
            return {}
        for c in cards:
            if c["ident"] == ident:
                loc = c["location"].lower()
                online = "zoom" in loc or "virtual" in loc or "webcast" in " ".join(c["types"]).lower()
                return self._card_detail(
                    {**shell, "description_hint": c["description"] or None},
                    {"end_date": c["end_date"], "location": c["location"], "online": online,
                     "types": c["types"], "categories": c["categories"], "href": c["href"]},
                    llm_call)
        return {}

    # -- calendar card ------------------------------------------------------ #
    def _card_detail(self, shell, meta, llm_call) -> Dict[str, Any]:
        title = shell.get("title") or ""
        types = meta.get("types") or []
        cats = meta.get("categories") or []
        href = meta.get("href") or ""
        is_congress = any("congress" in t.lower() for t in types)
        is_hosted = any("hosted training" in t.lower() for t in types)
        is_non_sccm = any("non" in t.lower() and "sccm event" in t.lower() for t in types)
        online = bool(meta.get("online"))

        res: Dict[str, Any] = {
            "event_type": _event_type(types),
            "end_date": meta.get("end_date"),
            "booking_url": href or None,
            "organiser_url": href or None,
            "pricing_tiers": [],
        }

        # Venue / city / region / format
        raw_loc = meta.get("location") or ""
        if is_congress:
            # Card "location" is the venue (San Diego Convention Center / Hilton ...).
            res["venue_name"] = raw_loc or None
            res["city"] = "San Diego"
            res["region"] = "California, USA"
            res["event_format"] = "in_person"
        elif online:
            res["event_format"] = "online"
        elif raw_loc:
            res.update(_split_location(raw_loc))
            if re.search(r"\(in-person\)", title, re.I):
                res["event_format"] = "in_person"
            elif re.search(r"hybrid", title, re.I):
                res["event_format"] = "hybrid"
            else:
                res["event_format"] = "in_person"

        # CPD / description from SCCM-hosted pages (webcasts link to sccm.org itself)
        desc = shell.get("description_hint") or ""
        if href.startswith(HOST) and "#" not in href and "/education-center/" in href:
            body = fetch_html(href, browser=getattr(self, "browser", None))
            if body:
                m = re.search(r"(\d+(?:\.\d+)?)\s*ACE\s*Credits?", _txt(body), re.I)
                if m:
                    res["cpd_points"] = float(m.group(1))
                    res["cpd_accredited"] = True
        if not desc and is_hosted:
            host = title.split("-", 1)[1].strip() if "-" in title else ""
            course = cats[0] if cats else title.split("-", 1)[0].strip()
            desc = (f"{course} hosted-training course run by {host} under the Society of "
                    f"Critical Care Medicine (SCCM) hosted-training programme.") if host else \
                   f"{course} hosted-training course listed on the SCCM conference calendar."
        res["description"] = desc or None

        # Specialty: SCCM-run education is critical care by definition. Only
        # third-party events get the LLM / classifier (they can be cardiology etc).
        specialty = None
        if is_non_sccm:
            specialty = self._llm_specialty(title, desc, llm_call) or classify_specialty(title, desc)
        res["specialty"] = specialty or DEFAULT_SPECIALTY
        return res

    @staticmethod
    def _llm_specialty(title: str, desc: str, llm_call) -> Optional[str]:
        prompt = (
            "Pick the single primary medical specialty of this event. Reply with strict JSON "
            '{"specialty": "<name>"} using a short standard name such as Intensive Care Medicine, '
            "Cardiology, Respiratory, Paediatrics, Anaesthetics, Nephrology. No other text.\n\n"
            f"Title: {title}\nDescription: {(desc or '')[:1500]}"
        )
        try:
            raw = llm_call(prompt)
        except Exception:
            return None
        if not raw:
            return None
        m = re.search(r"\{.*?\}", raw, re.S)
        if not m:
            return None
        try:
            val = json.loads(m.group(0)).get("specialty")
        except Exception:
            return None
        return val.strip() if isinstance(val, str) and 2 < len(val.strip()) < 60 else None

    # -- flagship ----------------------------------------------------------- #
    def _flagship(self, page, shell, meta) -> Dict[str, Any]:
        try:
            body = page.content()
        except Exception:
            body = ""
        text = _txt(body)
        res: Dict[str, Any] = {
            "event_type": "conference",
            "is_flagship": True,
            "end_date": meta.get("end_date"),
            "venue_name": meta.get("venue"),
            "booking_url": CONGRESS_URL,
            "organiser_url": CONGRESS_URL,
            "pricing_tiers": [],
            "event_format": "in_person",
            "specialty": DEFAULT_SPECIALTY,
            "description": shell.get("description_hint") or None,
            "abstract_open": False,
        }
        res.update(_split_location(meta.get("location") or ""))
        if re.search(r"accredited continuing education|ACE\)? credit", text, re.I):
            res["cpd_accredited"] = True
        return res
