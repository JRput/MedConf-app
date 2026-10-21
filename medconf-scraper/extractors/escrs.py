"""ESCRS (European Society of Cataract & Refractive Surgeons) meetings & events: Umbraco listing, plain HTTP.

`escrs.org/meetings-and-events/event-search` renders the upcoming events (default filter "Upcoming and Future") as
cards straight into the HTML: badge (ESCRS Events / Affiliated Events), title, an optional venue line and a date line
WITHOUT a year when the event is this year's ("30th October - 1st November"). The "load more" button is only emitted
when a result set exceeds one page (~96 cards: `?DateRange=All` shows it); the upcoming set is 7 today, so the plain
GET is complete. If the button ever appears, Phase A clicks it in the browser (unproven: nothing to click today).

Three kinds of card:
- Annual events (/escrs-annual-events/...): Winter Meeting and the numbered Congress. The escrs.org page is an empty shell;
  the real content is on the WordPress microsites wintermeeting.escrs.org / congress.escrs.org, used only when the
  microsite names the same year as the card. Registration there is not open yet ("Registration will open in December 2026"),
  so there are no fees. The Congress microsite publishes the Instructional Course submission deadline.
- Education events (/education-events/...), e.g. Vision to Venture: page -> /v2v/<city> page -> members.escrs.org/event/...
  registration page, whose Tribe Tickets block lists public EUR prices (two hops, PLAYBOOK coverage pattern 5).
- Affiliated events (other societies' congresses): the card links to the organiser (often wrapped in an Outlook SafeLink,
  unwrapped here). Detail is the card only; the organiser site is kept as `organiser_url`.
Cards for congresses more than ~3 years out are dropped by the family's MAX_FUTURE_DAYS.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import clip_venue, html_to_lines, sane_venue
from .wordpress_generic import WordPressGenericExtractor, split_location

_ROOT = "https://www.escrs.org"
_LISTING = _ROOT + "/meetings-and-events/event-search"
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_CARD_RE = re.compile(r'(?is)<a\s+class="card card-transition[^"]*"\s+href="([^"]+)"[^>]*>(.*?)</a>')
_MICROSITES = {"winter meeting": "https://wintermeeting.escrs.org/", "congress of the escrs": "https://congress.escrs.org/"}


def _clean(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag or ""))).replace("\xa0", " ").strip()


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_card_dates(text: str, today: Optional[date] = None, year_hint: Optional[int] = None) -> Optional[Tuple[str, str]]:
    """'30th October - 1st November' | '4 - 6 March 2027' | '17 March - 20 March 2027' | '15-19 October 2027'. Year-less
    dates take `year_hint` (from the URL) else the first year that puts the start on or after today. Pure."""
    today = today or date.today()
    t = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s*{_MON}?\s*(\d{{4}})?\s*(?:-|–|—|to)\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}\s*(\d{{4}})?", t, re.I)
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        mon2 = _MONTHS[m2[:3].lower()]
        mon1 = _MONTHS[m1[:3].lower()] if m1 else mon2
        year = int(y2) if y2 else (int(y1) if y1 else year_hint)
        for yr in ([year] if year else [today.year, today.year + 1]):
            a = _mk(yr - (1 if mon1 > mon2 and y2 and not y1 else 0), mon1, int(d1))
            b = _mk(yr, mon2, int(d2))
            if a and b and b >= a and (year or b >= today):
                return a.isoformat(), b.isoformat()
        return None
    m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}\s*(\d{{4}})?", t, re.I)
    if m:
        mon = _MONTHS[m.group(2)[:3].lower()]
        year = int(m.group(3)) if m.group(3) else year_hint
        for yr in ([year] if year else [today.year, today.year + 1]):
            a = _mk(yr, mon, int(m.group(1)))
            if a and (year or a >= today):
                return a.isoformat(), a.isoformat()
    return None


def unwrap_safelink(href: str) -> str:
    """Outlook SafeLinks wrap organiser URLs ('https://eur02.safelinks.protection.outlook.com/?url=<encoded>&data=...')."""
    href = _html.unescape(href or "").strip()
    if "safelinks.protection.outlook.com" in href:
        u = parse_qs(urlparse(href).query).get("url")
        if u:
            return unquote(u[0])
    return href


def parse_cards(html: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _CARD_RE.finditer(html or ""):
        href, inner = m.group(1), m.group(2)
        tm = re.search(r'(?is)<h5[^>]*class="card-title[^"]*"[^>]*>(.*?)</h5>', inner)
        if not tm:
            continue
        badge = _clean((re.search(r'(?is)card-pinned-top-end">(.*?)<', inner) or [None, ""])[1])
        ps = [_clean(x) for x in re.findall(r'(?is)<p class="fs-6[^>]*>(.*?)</p>', inner)]
        ps = [p for p in ps if p]
        date_line = next((p for p in ps if re.search(rf"\d.*{_MON}|{_MON}.*\d", p, re.I)), "")
        venue = next((p for p in ps if p != date_line), "")
        out.append({"url": unwrap_safelink(href) if href.startswith("http") else urljoin(_ROOT, _html.unescape(href)),
                    "title": _clean(tm.group(1)), "badge": badge, "date_line": date_line, "venue": venue})
    return out


def parse_tickets(html: str) -> List[Dict[str, Any]]:
    """Tribe Tickets items on a members.escrs.org event page: name, optional short note, symbol + amount. Pure."""
    tiers: List[Dict[str, Any]] = []
    seen = set()
    for chunk in re.split(r'(?i)<div\s+id="tribe-block-tickets-item-', html or "")[1:]:
        name_m = re.search(r'(?is)tickets-item-content-title[^>]*>(.*?)</div>', chunk)
        amt_m = re.search(r'(?is)tribe-currency-symbol">(.*?)</span>\s*<span class="tribe-amount">([0-9][0-9,.]*)</span>', chunk)
        if not name_m or not amt_m:
            continue
        sym = _html.unescape(_clean(amt_m.group(1)))
        cur = {"€": "EUR", "£": "GBP", "$": "USD"}.get(sym)
        if not cur:
            continue
        name = _clean(name_m.group(1))
        note_m = re.search(r'(?is)tickets-item-details-content[^>]*>(.*?)</div>', chunk)
        note = _clean(note_m.group(1)) if note_m else ""
        note = re.sub(r"(?i),?\s*requires approval", "", note).strip(" ,.")
        label = f"{name} · {note}" if note and len(note) <= 40 else name
        amount = float(amt_m.group(2).replace(",", ""))
        key = (label.lower(), amount)
        if key in seen:
            continue
        seen.add(key)
        tiers.append({"tier_label": label[:120], "price_gbp": amount, "currency": cur, "is_early_bird": False, "early_bird_deadline": None})
    return tiers


class EscrsExtractor(WordPressGenericExtractor):
    LISTING_URL = _LISTING
    SOCIETY = "ESCRS"
    DEFAULT_SPECIALTY = "Ophthalmology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    MAX_FUTURE_DAYS = 800                              # the 47th/48th Congress cards (2029/2030) carry a date and nothing else

    # ---- listing ----------------------------------------------------------------------------
    def _listing_html(self) -> Optional[str]:
        browser = getattr(self, "browser", None)
        html = None
        for attempt in range(3):
            html = fetch_html(_LISTING, browser=browser, expect_selector="#eventSearchResultsContainer")
            if html and "card card-transition" in html:
                break
            html = None
            time.sleep(2 * (attempt + 1))
        if html and 'id="LoadNextButton"' in html and browser is not None:     # more than one page of results: click through in the browser
            try:
                browser.navigate(_LISTING)
                for _ in range(8):
                    btn = browser.page.query_selector("#LoadNextButton")
                    if not btn or not btn.is_visible():     # absent or hidden: nothing more to load
                        break
                    before = browser.page.eval_on_selector_all("a.card-transition", "els => els.length")
                    btn.click(timeout=3000)
                    for _ in range(12):                    # poll up to ~6 s for the new cards to be appended
                        browser.page.wait_for_timeout(500)
                        if browser.page.eval_on_selector_all("a.card-transition", "els => els.length") > before:
                            break
                    else:
                        browser.page.wait_for_timeout(2500)   # count never grew: fall back to the old fixed wait
                html = browser.page.content()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"ESCRS: load-more click-through failed ({e}); using the first page only")
        return html

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._listing_html()
        if not html:
            return None
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen = set()
        cards = parse_cards(html)
        if not cards and 'id="eventSearchResultsContainer"' in html:
            self.verified_empty = "ESCRS event-search answered 200 with an empty upcoming result container"
        for c in cards:
            ym = re.search(r"-(20\d{2})$", urlparse(c["url"]).path.rstrip("/"))
            d = parse_card_dates(c["date_line"], today, int(ym.group(1)) if ym else None)
            if not d or d[1] < today.isoformat() or (date.fromisoformat(d[0]) - today).days > self.MAX_FUTURE_DAYS:
                continue
            if c["url"] in seen or re.search(r"(?i)\b(?:cancell?ed|postponed)\b", c["title"]):
                continue
            seen.add(c["url"])
            ext = not urlparse(c["url"]).netloc.lower().endswith("escrs.org")
            shells.append({"title": c["title"], "booking_url": c["url"], "source_url": c["url"], "start_date": d[0], "end_date": d[1],
                           "start_time": None, "venue_raw": c["venue"] or None, "category": c["badge"] or None,
                           "external": ext, "path": urlparse(c["url"]).path})
        logger.info(f"ESCRS: {len(shells)} upcoming shells from {len(cards)} cards")
        return shells or None

    # ---- detail -----------------------------------------------------------------------------
    @staticmethod
    def _event_type(shell: Dict[str, Any]) -> str:
        t = shell["title"].lower()
        if re.search(r"congress|meeting|symposium|conference|summit|forum", t):
            return "conference"
        if shell.get("path", "").startswith("/education-events") or re.search(r"weekend|masterclass|school|course|workshop|training|venture", t):
            return "course"
        return "conference"

    def _place(self, shell: Dict[str, Any], microsite_text: str = "") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        raw = (shell.get("venue_raw") or "").replace(" - ", ", ")
        m = re.search(r"(?:to be held|will take place|takes place)[^.]{0,60}?\bat\s+(?P<v>[^.]+?)\s+in\s+(?P<c>[A-Z][\w' -]+?),\s*(?P<k>[A-Z][\w ]+?)\.", microsite_text)
        if m:                                              # the microsite spells the place correctly (the card says "Eygpt")
            out.update({"venue_name": clip_venue(sane_venue(m.group("v"))), "city": m.group("c").strip(), "region": m.group("k").strip()})
        elif raw:
            v, c, k = split_location(raw)
            if not (v or c):                               # "Marriot Hotel, Budapest" / "IFEMA, Madrid, Spain": city last, country stripped
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                if k and parts and parts[-1] == k:
                    parts.pop()
                if len(parts) >= 2:
                    v, c = ", ".join(parts[:-1]), parts[-1]
                elif parts:
                    v = parts[0]
            if v:
                out["venue_name"] = clip_venue(sane_venue(v))
            if c:
                out["city"] = c
            if k:
                out["region"] = k
        if out.get("venue_name") or out.get("city"):
            out["event_format"] = "in_person"
        return {k: v for k, v in out.items() if v}

    def _microsite(self, shell: Dict[str, Any]) -> Tuple[Optional[str], str]:
        t = shell["title"].lower()
        url = next((u for k, u in _MICROSITES.items() if k in t), None)
        if not url:
            return None, ""
        html = fetch_html(url, browser=getattr(self, "browser", None))
        text = " ".join(html_to_lines(re.sub(r"(?is)<(script|style|svg|nav|footer|head)\b.*?</\1>", " ", html or "")))
        if not html or shell["start_date"][:4] not in text:      # the microsite is for another year's edition
            return None, ""
        return url, text

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": self.SOCIETY, "start_date": shell["start_date"], "end_date": shell["end_date"],
                               "event_type": self._event_type(shell), "specialty": self.DEFAULT_SPECIALTY, "pricing_tiers": []}
        html = page.content() if (page is not None and not shell.get("external")) else ""
        if shell.get("external"):
            out["organiser_url"] = shell["booking_url"]
            out.update(self._place(shell))
            out["description"] = self._blurb(shell)
            return out

        micro_url, micro_text = (None, "")
        if shell["path"].startswith("/escrs-annual-events"):
            micro_url, micro_text = self._microsite(shell)
        out.update(self._place(shell, micro_text))
        if micro_url:
            out["organiser_url"] = micro_url
            intro = re.search(r"(?:It is my (?:distinct )?pleasure|We are delighted|I am delighted)[^.]{20,400}\.", micro_text)
            m = re.search(r"Instructional Course Submission Deadline\s+(\d{1,2})\s+" + _MON + r"\s+(\d{4})", micro_text)
            if m:
                out["abstract_deadline"] = date(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1))).isoformat()
                out["abstract_open"] = out["abstract_deadline"] >= date.today().isoformat()
            else:
                am = re.search(r"Submit your abstract by (\d{1,2}) " + _MON, micro_text)
                if am:                                     # year-less: the next occurrence on/after today, before the event starts
                    d = parse_card_dates(f"{am.group(1)} {am.group(2)}", date.today())
                    if d and d[0] <= shell["start_date"]:
                        out["abstract_deadline"], out["abstract_open"] = d[0], True
            if intro:
                out["description"] = intro.group(0)[:600]
            elif micro_text:
                out["description"] = self._blurb(shell)
        else:
            tiers = self._education_tickets(html, shell)
            if tiers:
                out["pricing_tiers"] = tiers
            lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|nav|footer|head|header)\b.*?</\1>", " ", html))
            desc = next((l for l in lines if len(l) >= 90 and re.search(r"[.!?](\s|$)", l) and not re.match(r"(?i)^(?:explore|about cookies|we use cookies)", l)), None)
            out["description"] = (desc or self._blurb(shell))[:600]
        if not out.get("description"):
            out["description"] = self._blurb(shell)
        return out

    def _education_tickets(self, html: str, shell: Dict[str, Any]) -> List[Dict[str, Any]]:
        """page -> same-site /v2v/ page -> members.escrs.org registration page (public ticket prices)."""
        browser = getattr(self, "browser", None)
        reg = re.search(r'href="(https://members\.escrs\.org/event/[^"]+)"', html or "")
        if not reg:
            hops: List[str] = []
            for h in re.findall(r'href="((?:https://www\.escrs\.org)?/v2v/[^"#?]+)"', html or ""):
                if h not in hops:
                    hops.append(h)
            for h in sorted(hops, key=lambda x: -len(x))[:3]:       # the longest slug is the city page ("vision-to-venture-budapest")
                sub = fetch_html(urljoin(_ROOT, h), browser=browser)
                reg = re.search(r'href="(https://members\.escrs\.org/event/[^"]+)"', sub or "")
                if reg:
                    break
        if not reg:
            return []
        page_html = fetch_html(reg.group(1), browser=browser)
        return parse_tickets(page_html or "")

    @staticmethod
    def _blurb(shell: Dict[str, Any]) -> str:
        a, b = date.fromisoformat(shell["start_date"]), date.fromisoformat(shell["end_date"])
        when = f"{a.day} {a:%B %Y}" if a == b else (f"{a.day}-{b.day} {a:%B %Y}" if (a.month, a.year) == (b.month, b.year) else f"{a.day} {a:%B} - {b.day} {b:%B %Y}")
        return f"{shell['title']}, an ophthalmology meeting listed by ESCRS, on {when}. Programme and registration details have not been published yet."
