"""EURETINA (European Society of Retina Specialists) future meetings: WordPress family subclass, browser-first listing.

`euretina.org/future-meetings/` is an Elementor page: a "Schedule Of Upcoming Meetings" table with one row per
meeting (title, date range, "Venue, City, Country", an "Information" link when the meeting has its own microsite).
The table is in the rendered DOM, not in any API (the page makes no XHR/REST call for it), so Phase A loads the
page in the browser and parses that table. The page repeats the rows lower down in a mobile layout and then lists
past meetings; rows are deduped and only the first schedule block is read.

Rows without an "Information" link (Innovation Spotlight, the 28th and 29th Congress) have no page of their own;
they get a stable `<listing>#<slug>` URL and their detail is built from the row alone. Pages for 2027 meetings
publish no fee table yet, so tiers are empty (checked: /copenhagen-27/registration/ and /sfm-2027/registration/ do not exist).
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, pick_event_dates, split_location

_ROOT = "https://euretina.org"
_LISTING = _ROOT + "/future-meetings/"
_ANCHOR_RE = re.compile(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>')
_STRONG_P_RE = re.compile(r"(?is)<p[^>]*>\s*<strong>(.*?)</strong>\s*</p>")
_TBC_PREFIX_RE = re.compile(r"^(?:venue(?: and information)? tbc|information tbc|tbc)\s*,?\s*", re.I)


def _clean(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_schedule(html: str) -> List[Dict[str, Any]]:
    """Rows of the first 'Schedule Of Upcoming Meetings' table: title, dates text, venue text, link. Pure."""
    i = html.find("Schedule Of Upcoming Meetings")
    seg = html[i:] if i >= 0 else html
    rows: List[Dict[str, Any]] = []
    seen = set()
    # each row = <p><strong>Title</strong></p> ... <p>dates</p> ... <p>venue</p> ... [<a href>] <span>Information</span>
    heads = list(_STRONG_P_RE.finditer(seg))
    for n, m in enumerate(heads):
        end = heads[n + 1].start() if n + 1 < len(heads) else min(len(seg), m.end() + 4000)
        block = seg[m.end():end]
        ps = [_clean(x) for x in re.findall(r"(?is)<p[^>]*>(.*?)</p>", block)]
        ps = [p for p in ps if p]
        if len(ps) < 2:
            continue
        title = _clean(m.group(1))
        dates = pick_event_dates(ps[0])
        if not title or not dates:
            continue
        link = None
        lm = _ANCHOR_RE.search(block)
        if lm and "euretina.org" in lm.group(1):
            link = lm.group(1).split("#")[0]
        key = (title.lower(), dates[0])
        if key in seen:
            continue
        seen.add(key)
        rows.append({"title": title, "start": dates[0], "end": dates[1], "venue": ps[1], "link": link})
    return rows


class EuretinaExtractor(WordPressGenericExtractor):
    LISTING_URL = _LISTING
    SOCIETY = "EURETINA"
    DEFAULT_SPECIALTY = "Ophthalmology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    DEFAULT_EVENT_TYPE = "conference"

    def _listing_html(self) -> Optional[str]:
        browser = getattr(self, "browser", None)
        for attempt in range(3):
            try:
                if browser is not None:
                    browser.navigate(_LISTING)
                    try:
                        browser.page.wait_for_selector("text=Schedule Of Upcoming Meetings", timeout=15000)
                    except Exception:  # noqa: BLE001
                        pass
                    body = browser.page.content()
                else:
                    body = self._fetch(_LISTING)
                if body and "Schedule Of Upcoming Meetings" in body:
                    return body
            except Exception as e:  # noqa: BLE001
                logger.warning(f"EURETINA listing load {attempt + 1}/3 failed: {e}")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._listing_html()
        if not html:
            return None
        today = date.today()
        shells: List[Dict[str, Any]] = []
        for r in parse_schedule(html):
            if r["end"] < today.isoformat() or (date.fromisoformat(r["start"]) - today).days > self.MAX_FUTURE_DAYS:
                continue
            venue = _TBC_PREFIX_RE.sub("", r["venue"]).strip()
            url = r["link"] or f"{_LISTING}#{_slug(r['title'])}-{r['start'][:4]}"
            shells.append({"title": r["title"], "booking_url": url, "source_url": url, "start_date": r["start"], "end_date": r["end"],
                           "start_time": None, "venue_raw": venue or None, "category": None, "has_page": bool(r["link"])})
        logger.info(f"EURETINA schedule: {len(shells)} upcoming shells")
        return shells or None

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        if shell.get("has_page"):
            html = page.content() if page is not None else ""
            out = self.detail_from_html(html, shell, llm_call)
            if not (out.get("description") or "").strip():
                out["description"] = self._introduction(html)
        else:                                                    # no microsite yet: the table row is all there is
            out = {"society": self.SOCIETY, "event_type": "conference",
                   "specialty": self.DEFAULT_SPECIALTY, "pricing_tiers": []}
            v, c, k = split_location(shell.get("venue_raw"))
            for key, val in (("venue_name", v), ("city", c), ("region", k)):
                if val:
                    out[key] = val
            if v or c:
                out["event_format"] = "in_person"
        out["start_date"], out["end_date"] = shell["start_date"], shell["end_date"]
        if not (out.get("description") or "").strip():
            out["description"] = self._blurb(shell)
        return out

    @staticmethod
    def _introduction(html: str) -> Optional[str]:
        """Microsite pages open with an 'Introduction' heading followed by a few prose lines."""
        lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer|header)\b.*?</\1>", " ", html))
        for i, ln in enumerate(lines):
            if ln.strip().lower() == "introduction":
                prose = [l.strip() for l in lines[i + 1:i + 8] if len(l.strip()) > 40 and not re.match(r"(?i)details for registration", l.strip())]
                text = " ".join(prose[:3]).strip()
                return text[:600] if len(text) >= 60 else None
        return None

    @staticmethod
    def _blurb(shell: Dict[str, Any]) -> str:
        a, b = date.fromisoformat(shell["start_date"]), date.fromisoformat(shell["end_date"])
        when = f"{a.day} {a:%B %Y}" if a == b else (f"{a.day}-{b.day} {a:%B %Y}" if (a.month, a.year) == (b.month, b.year) else f"{a.day} {a:%B} - {b.day} {b:%B %Y}")
        return f"{shell['title']}, a EURETINA retina meeting on {when}. Programme and registration details have not been published yet."
