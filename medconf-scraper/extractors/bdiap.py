"""BDIAP (British Division of the International Academy of Pathology) future meetings: family subclass.

`/events/future_bdiap_meetings.aspx` is a Convio-style .aspx page: one editable-text block with a bullet list
("<a>Title</a> - held jointly with ..., 4-5 December 2026.") plus one paragraph for the biennial IAP Congress. Each
item links to its own detail page (`/events/<id>/<slug>`, which may redirect to `/annual_symposium/default.aspx`, or
`/study_days/<name>/default.aspx`). Items without a date ("more details to be announced soon") are dropped by the family.

Detail pages are thin: dates in an "Event Date:" block, venue only on the `./location.aspx` sub-page ("will take place
at 6 Alie Street, London E1 8QT (home of the Royal College of Pathologists)") and fees only on `./registration.aspx`
(plain `<table>`s: rows = delegate type, columns = EARLY BIRD / STANDARD or IAP Member / Non-IAP Member, a short
label above each table for member vs non-member). Both sub-pages are fetched here. A fee table headed with a past
year ("Registration Fees (2026)" on a 2027 event, "2027 registration will be announced soon") is stale and dropped;
the membership-dues table is not an event fee and is ignored.
"""
import html as _html
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, split_location, clip_venue

_CITIES = {"London", "Belfast", "Birmingham", "Manchester", "Leeds", "Glasgow", "Edinburgh", "Oxford", "Cardiff", "Newcastle", "Liverpool", "Cambridge", "Sheffield", "Bristol"}
_CHROME_RE = re.compile(r"(?i)use this area to add quick shortcuts to your favou?rite pages\.?")
_TABLE_RE = re.compile(r"(?is)<table\b.*?</table\s*>")
_ROW_RE = re.compile(r"(?is)<tr\b.*?</tr\s*>")
_CELL_RE = re.compile(r"(?is)<t[dh]\b.*?</t[dh]\s*>")
_PRICE_RE = re.compile(r"^(£|€|\$)\s?(\d[\d,]*(?:\.\d{1,2})?)$")
_TAKE_PLACE_RE = re.compile(r"(?i)will take place (?:at|in)\s+(.+?)(?:\.\s|\.$|$)")
_SKIP_HEAD_RE = re.compile(r"(?i)^(?:this event is primarily for:?|event date:?|download event to calendar|event|directions|save the date!?)$")


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


class BdiapExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://bdiap.org/events/future_bdiap_meetings.aspx"
    SOCIETY = "BDIAP"
    DEFAULT_SPECIALTY = "Pathology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    EVENT_LINK_RE = re.compile(r"^/(?:events/\d+/|study_days/[a-z_]+/default\.aspx)", re.I)
    CARD_SPLIT_RE = re.compile(r"(?i)<li\b|<p>(?=\s*(?:Save the date!\s*)?The\s*<a)")

    # ---- hooks -------------------------------------------------------------
    def venue_from_lines(self, lines: List[str], shell: Dict[str, Any]) -> Optional[str]:
        """The place line sits right under the title/date line on joint-meeting and congress pages
        ("ICC Belfast", "Fukuoka, Japan"); study-day pages have none (their venue is on ./location.aspx)."""
        title = (shell.get("title") or "").strip().lower()
        for idx in [i for i, l in enumerate(lines) if title and l.strip().lower() == title]:
            for l in lines[idx + 1: idx + 4]:
                if _SKIP_HEAD_RE.match(l) or l.strip().lower() == title:
                    if l.strip().lower() == title:
                        continue
                    break
                if re.match(r"(?i)^(?:home|meetings|calendar|events?|future bdiap meetings)$", l):
                    continue                                               # breadcrumb
                if re.search(r"\d{4}|\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b|\d{1,2}:\d{2}", l):
                    continue                                               # the date line
                if len(l) <= 60 and not l.endswith(":"):
                    return l
                break
        return None

    # ---- detail ------------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        base = (getattr(page, "url", None) or shell.get("booking_url") or self.LISTING_URL)
        out = self.detail_from_html(html, shell, llm_call)
        year = (out.get("start_date") or shell.get("start_date") or "")[:4]
        browser = getattr(self, "browser", None)
        subs = {}
        for name in ("location", "registration"):
            m = re.search(rf"""(?is)href=["'](\./{name}\.aspx)["']""", html)
            if m:
                subs[name] = fetch_html(urljoin(base, m.group(1)), browser=browser)
        if subs.get("location") and not out.get("venue_name"):
            self._apply_location(out, subs["location"])
        if out.get("city") and not out.get("event_format"):
            out["event_format"] = "in_person"
        if subs.get("registration"):
            tiers = self._fee_tables(subs["registration"], year)
            if tiers:
                out["pricing_tiers"] = tiers
        return out

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        lines = html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html))
        h1 = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1\s*>", html)
        place = self.venue_from_lines(lines, {**shell, "title": _txt(h1.group(1)) if h1 else shell.get("title")})                    # "ICC Belfast" / "Fukuoka, Japan" under the title
        if place:
            v, c, k = split_location(place)
            for key in ("venue_name", "city", "region"):
                out.pop(key, None)
            if not v and c and c.split()[-1] in _CITIES and len(c.split()) > 1:
                v, c = c, c.split()[-1]                                   # "ICC Belfast": venue + city
            if v:
                out["venue_name"] = clip_venue(v)
            if c:
                out["city"] = c
            if k:
                out["region"] = k
        if out.get("city") and re.search(r"(?i)discover where|take place|taking place|^(?:location|home|meetings)$", out["city"]):
            out.pop("city")                                    # link blurb "Discover where this Study Day is taking place"
        if out.get("venue_name") in _CITIES and not out.get("city"):
            out["city"] = out["venue_name"]
        if out.get("venue_name") and out.get("city") and out["venue_name"].endswith(out["city"]) and out["venue_name"] != out["city"]:
            out["city"] = out["city"]                           # "ICC Belfast" keeps venue, city Belfast
        elif out.get("venue_name") and not out.get("city"):
            last = out["venue_name"].split()[-1]
            if last in _CITIES:
                out["city"] = last
        if (out.get("city") or out.get("venue_name")) and not out.get("event_format"):
            out["event_format"] = "in_person"
        if out.get("city") in _CITIES and not out.get("region"):
            out["region"] = "United Kingdom"
        d = _CHROME_RE.sub("", out.get("description") or "").strip()
        if len(d) < 40:
            lines = [l for l in html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html))
                     if len(l) >= 80 and not _CHROME_RE.search(l) and not re.search(r"(?i)cookie|etiquette|registering", l)]
            d = lines[0][:600] if lines else ""
        if d:
            out["description"] = d
        else:
            out.pop("description", None)
        if not out.get("pricing_tiers"):                               # fees for the IAP congress live on its own website
            for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""", html):
                if re.search(r"(?i)congress website|book online for this event", _txt(m.group(2))) and "bdiap.org" not in m.group(1):
                    out["organiser_url"] = _html.unescape(m.group(1))
                    break
        return out

    @staticmethod
    def _apply_location(out: Dict[str, Any], html: str) -> None:
        text = " ".join(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html)))
        m = _TAKE_PLACE_RE.search(text)
        if not m:
            return
        raw = m.group(1)
        home = re.search(r"\((?:home of|at)\s+(?:the\s+)?([^)]+)\)", raw)
        raw = re.sub(r"\s*\([^)]*\)", "", raw).strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        city = next((c for p in parts for c in _CITIES if re.search(rf"\b{c}\b", p)), None)
        venue = home.group(1).strip() if home else (parts[0] if parts else None)
        if venue:
            out["venue_name"] = clip_venue(venue)
        if city:
            out["city"] = city
            out["region"] = "United Kingdom"
            out["event_format"] = "in_person"

    @staticmethod
    def _fee_tables(html: str, event_year: str) -> List[Dict[str, Any]]:
        body = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html)
        text = " ".join(html_to_lines(body))
        eb_deadline = None
        m = re.search(r"(?i)early bird[^.]{0,40}?until\s+(\d{2})\.(\d{2})\.(\d{4})", text)
        if m:
            eb_deadline = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        tiers: List[Dict[str, Any]] = []
        pos = 0
        for tm in _TABLE_RE.finditer(body):
            before = html_to_lines(body[pos:tm.start()])
            pos = tm.end()
            rows = [[_txt(c) for c in _CELL_RE.findall(r)] for r in _ROW_RE.findall(tm.group(0))]
            rows = [r for r in rows if r]
            if len(rows) < 2 or re.search(r"(?i)membership", rows[0][0]):
                continue                                                    # membership dues, not an event fee
            head_years = re.findall(r"\b(20\d\d)\b", " ".join(before[-1:] + rows[0]))
            if head_years and event_year and event_year not in head_years:
                continue                                                    # "Registration Fees (2026)" on a 2027 event: stale
            section = before[-1] if before and len(before[-1]) <= 45 and not _PRICE_RE.match(before[-1]) and not re.search(r"(?i)registration fees|^register$", before[-1]) else None
            for row in rows[1:]:
                for j, cell in enumerate(row[1:], start=1):
                    pm = _PRICE_RE.match(cell.replace(" ", ""))
                    if not pm or j >= len(rows[0]):
                        continue
                    col = rows[0][j].strip()
                    early = bool(re.search(r"(?i)early", col))
                    timing = "Early bird" if early else ("Standard" if re.search(r"(?i)standard|full", col) else None)
                    label = " · ".join(x for x in (section, row[0], timing or col) if x)
                    tiers.append({"tier_label": label, "price_gbp": float(pm.group(2).replace(",", "")), "currency": "GBP",
                                  "is_early_bird": early, "early_bird_deadline": eb_deadline if early else None})
        return tiers
