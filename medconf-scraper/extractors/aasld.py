"""AASLD (American Association for the Study of Liver Diseases) events: WordPress family subclass, Drupal JSON:API listing.

`aasld.org/events-and-webinars` is a Drupal 10 page whose list is loaded by JavaScript from the site's own search
index, `/jsonapi/index/events?page[limit]=..&sort=field_event_start` (the page's "load more" button pages that
same call). Phase A reads that JSON in the browser. Each record has `field_event_start/end` (ISO with offset, so
the first 10 characters are the local date), `field_location`, `field_link` (register link), `body`, and a path
alias for the detail page on aasld.org. The index lists only upcoming items.

Two things the index does NOT carry, both handled here:
- The Liver Meeting (the flagship) lives on its own microsite `/tlm-26/home`; it is discovered from the nav link
  on the events page, its dates and venue are read from the home page prose, and its fee grid from
  `/tlm-26/event-registration` (one block per member category, "Non-Member" and "Special Member Price" columns).
- Application-only programmes (e.g. the AGA-AASLD Academic Skills Workshop) are skipped: nothing to register for.
Webinars are included when dated; their LiverLearning page states "Cost $0.00" and is read for the fee.
USD throughout.
"""
import html as _html
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor

_ROOT = "https://www.aasld.org"
_LISTING = _ROOT + "/events-and-webinars"
_API = _ROOT + "/jsonapi/index/events?page%5Boffset%5D={off}&page%5Blimit%5D=50&sort=field_event_start"
_TLM_LINK_RE = re.compile(r'href="((?:https://www\.aasld\.org)?/tlm-\d+/home)"')
_APPLICATION_ONLY_RE = re.compile(r"applications?\s+must\s+be\s+submitted|apply\s+to\s+launch|selected\s+participants", re.I)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _day(s: Optional[str]) -> Optional[str]:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s or "")
    return m.group(1) if m else None


def _month_day(text: str, year: int) -> Optional[str]:
    m = re.search(r"(%s)\s+(\d{1,2})" % "|".join(m.capitalize() for m in _MONTHS), text)
    if not m:
        return None
    try:
        return date(year, _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))).isoformat()
    except ValueError:
        return None


def parse_tlm_home(html: str, url: str) -> Optional[Dict[str, Any]]:
    """The Liver Meeting microsite home page -> shell (title, dates, venue). None if any hard field is missing."""
    title = _text((re.search(r"(?is)<title>(.*?)</title>", html) or [None, ""])[1])
    ym = re.search(r"The Liver Meeting\W*\s*(20\d\d)", title) or re.search(r"The Liver Meeting\W*\s*(20\d\d)", html)
    text = _text(re.sub(r"(?is)<(script|style|nav|footer)\b.*?</\1>", " ", html))
    if not ym:
        return None
    year = int(ym.group(1))
    start = end = None
    m = re.search(r"begin\s+(?:one day earlier\s+)?on\s+\w+day,?\s+((?:%s)\s+\d{1,2}).{0,40}?conclude\s+on\s+\w+day,?\s+((?:%s)\s+\d{1,2})"
                  % ("|".join(x.capitalize() for x in _MONTHS), "|".join(x.capitalize() for x in _MONTHS)), text)
    if m:
        start, end = _month_day(m.group(1), year), _month_day(m.group(2), year)
    if not (start and end):
        m = re.search(r"taking place\s+((?:%s))\s+(\d{1,2})\s*[-–]\s*(\d{1,2})" % "|".join(x.capitalize() for x in _MONTHS), text)
        if m:
            start, end = _month_day(f"{m.group(1)} {m.group(2)}", year), _month_day(f"{m.group(1)} {m.group(3)}", year)
    vm = re.search(r"will be held at the\s+(.+?)\s+in\s+([A-Z][A-Za-z .]+?),\s*([A-Z][A-Za-z ]+?)\.", text)
    if not (start and end and vm):
        return None
    return {"title": f"The Liver Meeting {year}", "booking_url": url, "source_url": url, "start_date": start, "end_date": end,
            "start_time": None, "venue_raw": f"{vm.group(1)}, {vm.group(2)}, {vm.group(3)}", "category": "Conference",
            "kind": "tlm", "venue_name": vm.group(1), "city": vm.group(2)}


def parse_tlm_fees(html: str) -> List[Dict[str, Any]]:
    """Registration page -> tiers. Each `views-row` is one price block; the category description is the paragraph before it."""
    html = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", "", html)
    starts = [m.start() for m in re.finditer(r'class="views-row\b', html)]
    tiers: List[Dict[str, Any]] = []
    prev = 0
    for n, pos in enumerate(starts):
        before = html[prev:pos]
        paras = [_text(x) for x in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", before)]
        paras = [x for x in paras if len(x) > 60 and not x.lower().startswith("general in-person registration")]
        desc = paras[-1] if paras else ""
        block = html[pos:starts[n + 1] if n + 1 < len(starts) else pos + 6000]
        prev = pos
        low = desc.lower()
        if "caregiver" in low or "patient" in low:
            cat = "Patient or Advocate"
        elif "student" in low:
            cat = "Student"
        elif "do not desire" in low or "nurse practitioners" in low:
            cat = "Associate"
        elif "in training" in low or "trainee" in low:
            cat = "Trainee"
        elif "any other country" in low or "governing board" in low:
            cat = "Regular and International"
        else:
            continue
        vals = re.findall(r'(?is)<span[^>]*class="value[^"]*"[^>]*>\s*([^<]+?)\s*</span>\s*<p[^>]*class="title[^"]*"[^>]*>\s*([^<]+?)\s*</p>', block)
        for amount, kind in vals:
            m = re.match(r"^\$\s*([\d,]+(?:\.\d\d)?)$", amount.strip())
            if not m:
                continue
            who = "Member" if "member price" in kind.lower() else "Non-member"
            tiers.append({"tier_label": f"General Registration · {cat} · {who}", "price_gbp": float(m.group(1).replace(",", "")),
                          "currency": "USD", "is_early_bird": False, "early_bird_deadline": None})
    return tiers


_US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
              "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
              "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"}
_US_STATE_NAMES = {"alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida", "georgia", "hawaii",
                   "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
                   "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
                   "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
                   "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming"}


def us_location(raw: Optional[str], title: str = "") -> Optional[Dict[str, str]]:
    """'Sheraton Denver' (+ '(Denver)' in the title) / 'Four Seasons in Las Vegas, NV' / 'InterContinental Chicago Magnificent Mile, Chicago, Illinois'."""
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if parts and (parts[-1].upper() in _US_STATES or parts[-1].lower() in _US_STATE_NAMES):
        parts.pop()
    if not parts:
        return None
    venue, city = parts[0], parts[-1] if len(parts) > 1 else None
    if not city:
        m = re.search(r"\bin\s+([A-Z][A-Za-z .]+)$", venue)
        if m:
            venue, city = venue[:m.start()].strip(), m.group(1).strip()
    if not city:
        m = re.search(r"\(([A-Z][A-Za-z .]+)\)\s*$", title)
        city = m.group(1).strip() if m else None
    return {"venue_name": venue, "city": city or "", "region": "United States"}


class AasldExtractor(WordPressGenericExtractor):
    LISTING_URL = _LISTING
    SOCIETY = "AASLD"
    DEFAULT_SPECIALTY = "Gastroenterology & Hepatology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "USD"

    # ---- listing ----------------------------------------------------------
    def _browser_text(self, url: str) -> Optional[str]:
        browser = getattr(self, "browser", None)
        if browser is None:
            return None
        browser.navigate(url)
        return browser.page.inner_text("body")

    def _browser_html(self, url: str) -> Optional[str]:
        browser = getattr(self, "browser", None)
        if browser is None:
            return self._fetch(url)
        browser.navigate(url)
        return browser.page.content()

    def _records(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for off in range(0, 400, 50):
            data = None
            for attempt in range(3):
                try:
                    body = self._browser_text(_API.format(off=off))
                    data = json.loads(body or "{}")
                    if isinstance(data, dict) and "data" in data:
                        break
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"AASLD jsonapi offset {off} attempt {attempt + 1}/3 failed: {e}")
                time.sleep(2 * (attempt + 1))
            recs = (data or {}).get("data") or []
            out += [r for r in recs if isinstance(r, dict)]
            if len(recs) < 50:
                break
            time.sleep(self.REQUEST_GAP_S)
        return out

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for rec in self._records():
            a = rec.get("attributes") or {}
            title = _text(a.get("title") or "")
            start, end = _day(a.get("field_event_start")), _day(a.get("field_event_end"))
            alias = (a.get("path") or {}).get("alias") or ""
            if not (title and start and alias) or not a.get("status", True):
                continue
            end = end if end and end >= start else start
            if end < today:
                continue
            body = _text((a.get("body") or {}).get("processed") or (a.get("body") or {}).get("value") or "")
            link = (a.get("field_link") or {}).get("uri") or ""
            if not link and self._application_only(_ROOT + alias):
                logger.info(f"AASLD: skipping application-only programme '{title}'")
                continue
            st = re.search(r"T(\d{2}:\d{2})", a.get("field_event_start") or "")
            webinar = bool(re.match(r"(?i)webinar\b", title)) or "liverlearning" in link
            url = _ROOT + alias
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": start, "end_date": end,
                           "start_time": st.group(1) if st else None, "venue_raw": (a.get("field_location") or "").strip() or None,
                           "category": "Webinar" if webinar else None, "kind": "webinar" if webinar else "event",
                           "register_url": link or None, "body_text": body[:600]})
        tlm = self._tlm_shell()
        if tlm and tlm["end_date"] >= today and all(s["booking_url"] != tlm["booking_url"] for s in shells):
            shells.append(tlm)
        shells.sort(key=lambda s: s["start_date"])
        logger.info(f"AASLD: {len(shells)} upcoming shells")
        return shells or None

    def _application_only(self, url: str) -> bool:
        """An event with no register link whose page says applications are being taken is selection-only: nothing to book."""
        try:
            html = self._browser_html(url) or ""
        except Exception:  # noqa: BLE001
            return False
        return bool(_APPLICATION_ONLY_RE.search(_text(re.sub(r"(?is)<(script|style|nav|footer)\b.*?</\1>", " ", html))))

    def _tlm_shell(self) -> Optional[Dict[str, Any]]:
        try:
            listing = self._browser_html(_LISTING) or ""
            m = _TLM_LINK_RE.search(listing)
            if not m:
                return None
            url = m.group(1) if m.group(1).startswith("http") else _ROOT + m.group(1)
            shell = parse_tlm_home(self._browser_html(url) or "", url)
            if not shell:
                logger.warning("AASLD: The Liver Meeting home page did not yield dates + venue; skipped")
            return shell
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AASLD: The Liver Meeting microsite failed: {e}")
            return None

    # ---- detail -----------------------------------------------------------
    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        kind = shell.get("kind")
        if kind == "tlm":
            out = self._tlm_detail(html, shell, llm_call)
        else:
            try:
                out = self.detail_from_html(html, shell, llm_call)
            except (AttributeError, TypeError):          # family bug: JSON-LD "location" can be a list of names
                out = self.detail_from_html(re.sub(r'(?is)<script[^>]+application/ld\+json[^>]*>.*?</script>', " ", html), shell, llm_call)
            if kind != "webinar":
                loc = us_location(shell.get("venue_raw"), shell["title"])
                if loc:
                    out["venue_name"] = loc["venue_name"]
                    if loc["city"]:
                        out["city"] = loc["city"]
                    out["region"] = loc["region"]
                    out["event_format"] = "in_person"
            self._early_bird_dates(out, html, shell)
            nm = re.search(r"((?:junior investigator.s )?call for abstracts will be announced[^.]*\.)", _text(html), re.I)
            if nm and not out.get("abstract_deadline"):
                out["abstract_deadline_note"] = nm.group(1).strip().capitalize()
            cm = re.search(r"(\d+(?:\.\d+)?)\s+AMA PRA Category 1 Credit", _text(html))
            if cm and out.get("cpd_points") is None:
                out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
            if kind == "webinar":
                out["event_type"], out["event_format"] = "workshop", "online"
                out.pop("venue_name", None)
                out.pop("city", None)
                out.pop("region", None)
                if shell.get("register_url") and not out.get("pricing_tiers"):
                    tier = self._webinar_fee(shell["register_url"])
                    if tier:
                        out["pricing_tiers"] = [tier]
        out["start_date"], out["end_date"] = shell["start_date"], shell["end_date"]
        return out

    @staticmethod
    def _early_bird_dates(out: Dict[str, Any], html: str, shell: Dict[str, Any]) -> None:
        """Fee-table column header 'Early Bird (1/6)' = US month/day, the last such date before the event starts."""
        m = re.search(r"Early Bird\s*\((\d{1,2})/(\d{1,2})\)", _text(html))
        if not m:
            return
        start = date.fromisoformat(shell["start_date"])
        for y in (start.year, start.year - 1):
            try:
                d = date(y, int(m.group(1)), int(m.group(2)))
            except ValueError:
                return
            if d < start:
                for t in out.get("pricing_tiers") or []:
                    if t.get("is_early_bird") and not t.get("early_bird_deadline"):
                        t["early_bird_deadline"] = d.isoformat()
                return

    def _tlm_detail(self, home_html: str, shell: Dict[str, Any], llm_call) -> Dict[str, Any]:
        out = self.detail_from_html(home_html, {**shell, "venue_raw": shell.get("venue_raw")}, llm_call)
        out["event_type"] = "conference"
        out["venue_name"], out["city"], out["region"] = shell["venue_name"], shell["city"], "United States"
        out["event_format"] = "in_person"
        reg_url = shell["booking_url"].rsplit("/", 1)[0] + "/event-registration"
        tiers: List[Dict[str, Any]] = []
        try:
            # the rendered page only keeps the default category tab; the server HTML carries every category block
            tiers = parse_tlm_fees(fetch_html(reg_url, browser=getattr(self, "browser", None)) or "")
            if len(tiers) < 5:
                tiers = max(tiers, parse_tlm_fees(self._browser_html(reg_url) or ""), key=len)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AASLD TLM fee page failed: {e}")
        if tiers:
            out["pricing_tiers"] = tiers
        text = _text(re.sub(r"(?is)<(script|style|nav|footer)\b.*?</\1>", " ", home_html))
        m = re.search(r"The Liver Meeting\W+\(TLM\)[^.]{0,200}\.|The Liver Meeting.{0,40}2026 will be held at[^.]+\.", text)
        out["description"] = (m.group(0) if m else out.get("description") or "")[:600] or None
        out["booking_url"] = shell["booking_url"]
        return out

    def _webinar_fee(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            html = fetch_html(url, browser=getattr(self, "browser", None)) or ""
        except Exception:  # noqa: BLE001
            return None
        lines = html_to_lines(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html))
        for i, ln in enumerate(lines):
            if ln.strip().lower() == "cost" and i + 1 < len(lines):
                m = re.match(r"^\$\s*([\d,]+(?:\.\d\d)?)$", lines[i + 1].strip())
                if m:
                    return {"tier_label": "Webinar · Registration", "price_gbp": float(m.group(1).replace(",", "")),
                            "currency": "USD", "is_early_bird": False, "early_bird_deadline": None}
        return None
