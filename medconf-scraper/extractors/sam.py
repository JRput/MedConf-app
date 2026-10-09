"""SAM (Society for Acute Medicine) events: WordPress family subclass (Events Manager).

Two site quirks, both handled here:
- `/sam-events/` shows only ~7 featured events; the full list (about 30, mostly FAMUS / PoCUS courses)
  is on `/events/categories/famus/` and `/events/categories/other-events/`. The listing unions the three.
- Listing cards split the date into "9 / Oct / 2026" spans, so card dates are unreliable. Every event page's
  H1 carries title, date and place ("FAMUS Course, 9 October 2026, Wirral") and its meta description starts
  "09/10/2026 - 11/10/2026 @ All Day"; the listing reads those from each event page.
The site also embeds Cloudflare's passive `jsd/main.js` beacon in every real page, which `http_fetch`
mistakes for a challenge interstitial, so `_fetch` reads the browser's own page when httpx is refused.
"""
import html as _html
import re
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import _COUNTRIES, WordPressGenericExtractor, clip_venue, pick_event_dates, split_location

_ROOT = "https://www.acutemedicine.org.uk"
_LISTINGS = ["/sam-events/", "/events/categories/famus/", "/events/categories/other-events/"]
_EVENT_HREF_RE = re.compile(r"""href=["'](https://www\.acutemedicine\.org\.uk/sam-events/[a-z0-9][a-z0-9-]*/)["']""", re.I)
_H1_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_EM_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(20\d{2})(?:\s*-\s*(\d{2})/(\d{2})/(20\d{2}))?\s*@")


_EXTRA_COUNTRIES = {"Bangladesh", "India", "Pakistan", "Nepal", "Sri Lanka", "Egypt", "Nigeria", "Kenya", "Malaysia", "Dubai", "Saudi Arabia", "Qatar", "Oman"}
_POSTCODE_TAIL_RE = r"\s+[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$"
_POSTCODE_RE = r"[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}"
_EARLY_RE = re.compile(r"\u00a3\s*([\d,]+)\s+until\s+(\d{1,2} [A-Z][a-z]+ 20\d\d),?\s+increasing to\s+\u00a3\s*([\d,]+)")


def _clean_label(t: str) -> str:
    t = re.sub(r"^\W*(?:for|when|if)\s+", "", t.strip(), flags=re.I)
    t = re.sub(r"[\s,;:(){}*\u2013\u2014-]+$", "", re.sub(r"^[\s,;:(){}*\u2013\u2014-]+", "", t))
    t = re.sub(r"\s*[\u2013\u2014-]\s+.*$", "", t)                # "for SAM members - accommodation included" -> "SAM members"
    t = re.sub(r"[\s,;]*\b(?:or|and)$", "", t).strip(" ,;().")
    return t[:60]


def _row_tiers(row: str) -> List[Dict[str, Any]]:
    """'Both days: £500' / '£350 for each course, or £600 when purchased together' / 'DAY 1 ... £200 (NNUH) £250 External'."""
    ms = list(re.finditer(r"\u00a3\s*([\d,]+(?:\.\d\d)?)", row))
    out: List[Dict[str, Any]] = []
    prefix = _clean_label(re.sub(r"^(?:course\s+)?(?:costs?|fees?|price)\s*:?", "", row[:ms[0].start()], flags=re.I)) if ms else ""
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(row)
        suffix = _clean_label(row[m.end():end])
        bits = [b for b in ([prefix] if (prefix and (len(ms) == 1 or i >= 0)) else []) + ([suffix] if suffix else []) if b]
        if len(ms) == 1 and prefix and suffix:
            bits = [prefix]
        label = " \u00b7 ".join(dict.fromkeys(bits)) or "Standard"
        out.append({"tier_label": f"Cost \u00b7 {label}", "price_gbp": float(m.group(1).replace(",", "")), "currency": "GBP",
                    "is_early_bird": False, "early_bird_deadline": None})
    return out


class SamExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/sam-events/"
    SOCIETY = "SAM"
    DEFAULT_SPECIALTY = "Acute Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    def _fetch(self, url: str) -> Optional[str]:
        page = getattr(getattr(self, "browser", None), "page", None)
        if page is None:
            return fetch_html(url, browser=None)
        for attempt in range(3):
            try:
                page.goto(url, wait_until="load", timeout=30000)
                html = page.content()
                if html and len(html) > 2000 and "Just a moment" not in html[:3000]:
                    return html
            except Exception as e:  # noqa: BLE001
                logger.warning(f"SAM browser fetch attempt {attempt + 1}/3 failed for {url}: {e}")
            time.sleep(2 * (attempt + 1))
        return None

    @staticmethod
    def _dates(html: str, title: str):
        m = _EM_DATE_RE.search(html)
        if m:
            d, mo, y, d2, mo2, y2 = m.groups()
            s = f"{y}-{mo}-{d}"
            return s, (f"{y2}-{mo2}-{d2}" if d2 else s)
        return pick_event_dates(re.sub(r"\s*&\s*", "-", title))

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        urls: List[str] = []
        for path in _LISTINGS:
            html = self._fetch(_ROOT + path)
            time.sleep(self.REQUEST_GAP_S)
            for u in _EVENT_HREF_RE.findall(html or ""):
                if u not in urls:
                    urls.append(u)
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for u in urls:
            html = self._fetch(u)
            time.sleep(self.REQUEST_GAP_S)
            if not html:
                continue
            hm = _H1_RE.search(html)
            title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", hm.group(1)))).strip() if hm else ""
            dates = self._dates(html, title)
            if not title or not dates or (dates[1] or dates[0]) < today:
                continue
            sold_out = bool(re.search(r"sold out|fully booked|course is full|no places", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)[:200000], re.I))
            shells.append({"title": title, "booking_url": u, "source_url": u, "start_date": dates[0], "end_date": dates[1],
                           "start_time": None, "venue_raw": None, "category": None,
                           "is_sold_out": sold_out})                       # llm_agent's merge reads is_sold_out from the shell only
        logger.info(f"SAM: {len(shells)} upcoming of {len(urls)} event pages")
        return shells or None

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        lines = html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html))
        tail = (shell.get("title") or "").rsplit(",", 1)[-1].strip()
        is_country = tail in _COUNTRIES or tail in _EXTRA_COUNTRIES
        hy = re.match(r"^([A-Z][a-z]+)\s*&\s*online$", tail)
        # venue: "Venue: Mercure Parkway Sheffield, Britannia Way, Catcliffe, Sheffield, S60 5BD" (sometimes mid-line)
        vtxt = None
        for ln in lines:
            m = re.search(r"\b(?:venue|where)\s*:\s*(.+)$", ln, re.I)
            if m:
                vtxt = re.sub(r"\s*\((?:free|parking)[^)]*\)\s*$", "", m.group(1)).strip()
                break
        if vtxt:
            parts = [p.strip(" .") for p in vtxt.split(",") if p.strip(" .")]
            parts = [re.sub(_POSTCODE_TAIL_RE, "", p).strip() for p in parts]
            parts = [p for p in parts if p and not re.fullmatch(_POSTCODE_RE, p)]
            if parts and not out.get("venue_name"):
                out["venue_name"] = clip_venue(parts[0])
            cand = parts[-1] if len(parts) >= 2 else None
            if cand and not re.search(r"NHS|Trust|Hospital|University|Centre|Road|Rd\b|Street|\d|\(", cand) and (not out.get("city") or re.search(r"NHS|Trust|Hospital|\d", out["city"])):
                out["city"] = cand
        if (not out.get("city") or re.search(r"NHS|Trust|Hospital|\d", out["city"])) and not is_country \
                and 2 < len(tail) <= 25 and not re.search(r"[&\d]|online", tail, re.I):
            out["city"] = tail                                     # H1 ends with the place: "FAMUS Course, 18 November 2026, Walsall"
        if hy and not out.get("city"):
            out["city"], out["event_format"] = hy.group(1), "hybrid"        # "..., Cambridge & online"
        if is_country and not out.get("region"):
            out["region"] = tail                                   # "Acute Medicine & Critical Care Conference, ..., Bangladesh"
        if "(" in (out.get("venue_name") or "") and ")" not in out["venue_name"]:
            out["venue_name"] = out["venue_name"].split("(")[0].strip(" ,")      # clip_venue cut a bracket in half
        if (out.get("venue_name") or out.get("city") or out.get("region")) and not out.get("event_format"):
            out["event_format"] = "in_person"
        if out.get("city") and not out.get("region") and out.get("event_format") == "in_person":
            out["region"] = "United Kingdom"
        # fees: a Cost/Fees/Price line (inline or followed by 'Both days: £500' rows)
        tiers: List[Dict[str, Any]] = []
        for i, ln in enumerate(lines):
            m = re.match(r"^(?:course\s+)?(?:costs?|fees?|price)\s*:?\s*(.*)$", ln, re.I)
            if not m or not (m.group(1) or "\u00a3" in " ".join(lines[i + 1:i + 3])):
                continue
            rows = ([m.group(1)] if m.group(1) else []) + lines[i + 1:i + 7]
            for row in rows:
                if re.match(r"^(?:view|to book|application|book|register|further|full details)", row, re.I):
                    break
                tiers += _row_tiers(row)
            break
        if not tiers:
            m = _EARLY_RE.search(" ".join(lines))
            if m:
                try:
                    dl = datetime.strptime(m.group(2), "%d %B %Y").date().isoformat()
                except ValueError:
                    dl = None
                tiers = [{"tier_label": "Cost \u00b7 Early bird", "price_gbp": float(m.group(1).replace(",", "")), "currency": "GBP",
                          "is_early_bird": True, "early_bird_deadline": dl},
                         {"tier_label": "Cost \u00b7 Standard", "price_gbp": float(m.group(3).replace(",", "")), "currency": "GBP",
                          "is_early_bird": False, "early_bird_deadline": None}]
        if tiers and len(tiers) >= len(out.get("pricing_tiers") or []):
            out["pricing_tiers"] = tiers
        return out
