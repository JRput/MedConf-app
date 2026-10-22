"""EULAR (European Alliance of Associations for Rheumatology) events directory: eular.org/event.

eular.org is an Odoo website. `/event?date=upcoming` lists ~12 `<article>` cards per page, `/event/page/N?...` walks the
rest (19 upcoming events on 2 pages in Oct 2026). Each card has the title (`itemprop="name"`), a start `datetime`
(UTC, so it can be a day off for events stored at local midnight), a "City, Country" line (or TBC/TBD) and an optional
tag ("EULAR-endorsed course"). Card links point at `/event/<slug>-<id>/register`.

The event page carries the real local dates in the sidebar (`<h5>` "Thursday, 22 October 2026" ... "Saturday, 24 October
2026" and the end time; Europe/Zurich), the organiser, and a "Go to website" button to wherever registration lives.
Placeholder events are stored 00:00 -> 00:00 (end exclusive) and get end date minus one day. The eular.org page has no prose description.

Organiser pages: the sidebar "Go to website" link is stored as `organiser_url`. EULAR's own courses register on
edu.eular.org (Moodle; public `Cost: EUR 650`), fetched with the validated fetcher. For every other organiser site ONE
validated hop (check_url_safe + fetch_validated, hostname via urlparse) reads the landing page for a description (meta/og,
else the first real paragraph; text naming a year other than the event's year is discarded) and for fees (JSON-LD
offers or a plain fee table). If the landing page has no fees, ONE more hop follows a registration/fees/prices link on
the SAME hostname. At most 20 extra requests per run (both hops count). Without organiser prose the description is a
one-line template built only from page fields.
"""
import html as _html
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from logger import logger
from safe_fetch import check_url_safe, fetch_validated

from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables

try:                                              # site timezone for the UTC card datetimes
    from zoneinfo import ZoneInfo
    _ZURICH = ZoneInfo("Europe/Zurich")
except Exception:                                 # pragma: no cover - tzdata missing
    _ZURICH = None

_ROOT = "https://www.eular.org"
_LIST_URL = _ROOT + "/event?search=&date=upcoming&tags=&type=all&country=all"
_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
_ARTICLE_RE = re.compile(r"(?is)<article\b.*?</article>")
_LONG_DATE_RE = re.compile(r"(?i)(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_UNKNOWN_PLACE_RE = re.compile(r"(?i)^\s*(?:tbc|tbd|tba|to be (?:confirmed|determined|announced)|-*)\s*$")


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag or ""))).replace("\xa0", " ").strip()


def _iso(d: int, month: str, y: int) -> Optional[str]:
    m = _MONTHS.get(month.lower())
    try:
        return date(y, m, d).isoformat() if m else None
    except ValueError:
        return None


def _card_start(utc_text: str) -> Optional[str]:
    """Card `datetime="2027-04-07 22:00:00"` is UTC; the site shows Europe/Zurich."""
    try:
        dt = datetime.strptime(utc_text.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (dt.astimezone(_ZURICH) if _ZURICH else dt).date().isoformat()


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """One listing page -> one dict per card (pure)."""
    out: List[Dict[str, Any]] = []
    for card in _ARTICLE_RE.findall(html or ""):
        name = re.search(r'itemprop="name">(.*?)</span>', card, re.S)
        when = re.search(r'<time itemprop="startDate" datetime="([^"]+)"', card)
        if not name or not when:
            continue
        start = _card_start(when.group(1))
        # the card is wrapped by <a href="/event/...">, which sits just before <article>
        out.append({"title": _txt(name.group(1)), "start_date": start, "card": card})
    return out


def card_links(html: str) -> List[str]:
    return re.findall(r'<a class="text-decoration-none" href="(/event/[^"]+)"', html or "")


def split_place(raw: str) -> Dict[str, Optional[str]]:
    """"Belgrade, Serbia" -> city/region; TBC/TBD -> nothing."""
    raw = (raw or "").strip(" -")
    if _UNKNOWN_PLACE_RE.match(raw):
        return {}
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        return {"city": parts[0], "region": parts[-1]}
    return {"city": parts[0]} if parts else {}


def event_type_for(title: str, tag: str = "") -> str:
    t = f"{title} {tag}".lower()
    if re.search(r"\b(congress|conference|symposium|meeting)\b", t):
        return "conference"
    if re.search(r"\b(workshop|webinar|seminar)\b", t):
        return "workshop"
    return "course"


def parse_sidebar(html: str) -> Dict[str, Any]:
    """Event page -> {start_date, end_date, start_time, place, organiser_url} (pure)."""
    out: Dict[str, Any] = {}
    block = re.search(r"(?is)Date\s*(?:&amp;|&)\s*Time</h6>(.*?)<h6[^>]*>\s*Location", html or "")
    if block:
        seg = block.group(1)
        days = [m for h in re.findall(r"(?is)<h5[^>]*>(.*?)</h5>", seg) for m in [_LONG_DATE_RE.search(_txt(h))] if m]
        if days:
            out["start_date"] = _iso(int(days[0].group(1)), days[0].group(2), int(days[0].group(3)))
        if len(days) >= 2:
            out["end_date"] = _iso(int(days[1].group(1)), days[1].group(2), int(days[1].group(3)))
        end_t = re.search(r'date_end">\s*(\d{1,2}):(\d{2})\s*<', seg)
        if end_t and out.get("end_date") and out.get("start_date") and end_t.group(0) and (end_t.group(1), end_t.group(2)) == ("00", "00") \
                and out["end_date"] > out["start_date"]:
            out["end_date"] = (date.fromisoformat(out["end_date"]) - timedelta(days=1)).isoformat()   # midnight end is exclusive
    cal = re.search(r"dates=(\d{8})T(\d{2})(\d{2})\d{2}%2F", html or "")
    if cal and (cal.group(2), cal.group(3)) != ("00", "00"):
        out["start_time"] = f"{cal.group(2)}:{cal.group(3)}"
    place = re.search(r'(?is)<h6[^>]*>\s*Location</h6>.*?<span itemprop="name">(.*?)</span>', html or "")
    if place:
        out["place"] = _txt(place.group(1))
    m = re.search(r'(?is)<a\b[^>]*href="(https?://[^"]+)"[^>]*>\s*Go to website\s*</a>', html or "")
    if m:
        out["organiser_url"] = _html.unescape(m.group(1))
    return out


_CTA_RE = re.compile(r"(?i)register|go to website|submit|sign in|cookie|privacy|terms (?:of|and)|all rights reserved|javascript|add to calendar|subscribe|newsletter")


_CONTACT_RE = re.compile(r"(?i)^(?:congress )?venue\b|\bTel\b|\bFax\b|\bOffice\b|@|\+\d{2}|©|\bViale\b|\bStreet\b")


def _plausible(t: str) -> bool:
    letters = [c for c in t[:80] if c.isalpha()]
    shouting = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.4
    label = bool(re.match(r"^[^.]{0,45}:\s", t))                  # "Executive director of the Course: ..." is a field, not prose
    return len(t.split()) >= 10 and not (_CTA_RE.search(t) or _CONTACT_RE.search(t) or shouting or label)


def pick_description(html: str, whole_page: bool = False) -> Optional[str]:
    """meta/og description, else the first real paragraph of the event body (>= 60 chars, not a CTA line) (pure)."""
    for pat in (r'<meta[^>]+(?:property="og:description"|name="description")[^>]*content="([^"]+)"',
                r'<meta[^>]+content="([^"]+)"[^>]*(?:property="og:description"|name="description")'):
        m = re.search(pat, html or "")
        if m and len(_txt(m.group(1))) >= 60 and _plausible(_txt(m.group(1))):
            return _txt(m.group(1))[:600]
    if whole_page:                                    # third-party organiser page: drop chrome, take the first real paragraph
        scope = re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer|aside|form)\b.*?</\1\s*>", " ", html or "")
    else:
        body = re.search(r'(?is)itemprop="description">(.*?)</span>\s*</div>', html or "")
        scope = body.group(1) if body else ""
    for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", scope):
        t = _txt(p)
        if len(t) >= 60 and _plausible(t):
            return t[:600]
    return None


def year_conflict(desc: str, start: Optional[str]) -> bool:
    """True when the text names a 4-digit year (2020-2039) that is not the event's start year (pure)."""
    if not desc or not start:
        return False
    return any(y != start[:4] for y in re.findall(r"\b(20[23]\d)\b", desc))


def fee_link(html: str, base_url: str) -> Optional[str]:
    """Same-host link whose text mentions registration/fees/prices (pure)."""
    host = (urlparse(base_url).hostname or "").lower()
    for m in re.finditer(r"""(?is)<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a\s*>""", html or ""):
        if re.search(r"(?i)registration|fees|prices|tarif|register", _txt(m.group(2))):
            u = urljoin(base_url, _html.unescape(m.group(1)))
            if urlparse(u).scheme in ("http", "https") and (urlparse(u).hostname or "").lower() == host and u.split("#")[0] != base_url:
                return u
    return None


def facts_description(title: str, tag: str, start: Optional[str], end: Optional[str], place: Dict[str, Any]) -> str:
    """Last resort, built only from fields on the page: '<tag or EULAR event> <title> ...'. No claims beyond the page."""
    when = ""
    if start:
        d0 = date.fromisoformat(start)
        when = f" on {d0.day} {d0.strftime('%B %Y')}"
        if end and end != start:
            d1 = date.fromisoformat(end)
            when = f" from {d0.day} {d0.strftime('%B')} to {d1.day} {d1.strftime('%B %Y')}"
    where = f" in {place['city']}, {place['region']}" if place.get("city") and place.get("region") else (f" in {place['city']}" if place.get("city") else "")
    kind = tag or "EULAR event"
    return f"{kind}: {title}{when}{where}."


def offers_tiers(html: str) -> List[Dict[str, Any]]:
    """JSON-LD `offers` (price + priceCurrency) or a public fee table -> sanity-checked tiers (pure). EUR unless stated."""
    tiers: List[Dict[str, Any]] = []
    for blk in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or ""):
        for m in re.finditer(r'"price"\s*:\s*"?([\d.]+)"?\s*,\s*"priceCurrency"\s*:\s*"([A-Z]{3})"', blk):
            tiers.append({"tier_label": "Registration · Standard", "price_gbp": float(m.group(1)), "currency": m.group(2),
                          "is_early_bird": False, "early_bird_deadline": None})
    if not tiers:
        tiers = parse_pricing_tables(html or "", default_currency="EUR")
    ok, seen = [], set()
    for t in tiers:
        t = dict(t, tier_label="Registration · " + (t.get("tier_label") or "").split(" · ")[-1].strip())   # keep the row label, drop page headings
        try:
            amt = float(t["price_gbp"])
        except (TypeError, ValueError):
            continue
        if not (20 <= amt <= 10000) or t.get("currency") not in ("EUR", "USD", "GBP", "CHF", "TRY") or len(t.get("tier_label") or "") > 120:
            continue
        k = (t["tier_label"], amt)
        if k not in seen:
            seen.add(k)
            ok.append(t)
    today = date.today().isoformat()
    ok = [t for t in ok if not (t.get("early_bird_deadline") and t["early_bird_deadline"] < today)           # early rate already over
          and not re.search(r"(?i)accommodation|hotel|night|dinner|gala|^registration · (?:eur|usd)\b|^registration · \W*$", t["tier_label"])]
    by_label: Dict[str, set] = {}
    for t in ok:
        by_label.setdefault(t["tier_label"].lower(), set()).add(t["price_gbp"])
    ok = [t for t in ok if len(by_label[t["tier_label"].lower()]) == 1]       # same label, different prices: category lost, ambiguous
    return ok[:20]


def moodle_cost(html: str) -> Optional[Dict[str, Any]]:
    """edu.eular.org course page -> {"currency": "EUR", "amount": 650.0} from the `Cost:` row (pure)."""
    text = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>", " ", html or "")
    lines = [l for l in (_txt(x) for x in re.split(r"<[^>]+>", text)) if l]
    for i, ln in enumerate(lines):
        if ln.rstrip(":").lower() == "cost" and i + 1 < len(lines):
            m = re.match(r"(?i)^([A-Z]{3})\s*([\d][\d,.\s']*)$", lines[i + 1])
            if m:
                try:
                    return {"currency": m.group(1).upper(), "amount": float(re.sub(r"[,\s']", "", m.group(2)))}
                except ValueError:
                    return None
    return None


class EularExtractor(BaseExtractor):
    SOCIETY = "EULAR"
    DEFAULT_SPECIALTY = "Rheumatology"
    MAX_PAGES = 6
    MAX_ORGANISER_HOPS = 20          # extra requests per run, third-party organiser pages
    _hops = 0
    REQUEST_GAP_S = 1.0

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells: List[Dict[str, Any]] = []
        seen = set()
        self._hops = 0
        url = _LIST_URL
        for pg in range(1, self.MAX_PAGES + 1):
            html = fetch_html(url, browser=getattr(self, "browser", None))
            if not html or "o_wevent" not in html:
                if pg == 1:
                    return None
                break
            links = card_links(html)
            cards = parse_listing(html)
            if len(links) != len(cards):
                logger.warning(f"EULAR: page {pg} has {len(cards)} cards but {len(links)} links")
            for link, c in zip(links, cards):
                full = _ROOT + _html.unescape(link)
                if full in seen or re.search(r"(?i)cancel|postpone", c["title"]):
                    continue
                seen.add(full)
                place = re.search(r'text-muted">(.*?)</span>', c["card"], re.S)
                tag = re.search(r'<span class="badge[^>]*>\s*<span>(.*?)</span>', c["card"], re.S)
                shells.append({"title": c["title"], "booking_url": full, "source_url": full, "start_date": c["start_date"],
                               "venue_raw": _txt(place.group(1)).strip("- ") if place else None,
                               "category": _txt(tag.group(1)) if tag else None})
            nxt = re.search(r'href="(/event/page/%d\?[^"]+)"' % (pg + 1), html)
            if not nxt:
                break
            url = _ROOT + _html.unescape(nxt.group(1))
            time.sleep(self.REQUEST_GAP_S)
        logger.info(f"EULAR: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    @staticmethod
    def _is_eular_moodle(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return host == "edu.eular.org"

    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = fetch_html(shell["booking_url"], browser=getattr(self, "browser", None), loaded_page=page) or ""
        title = shell.get("title") or ""
        out: Dict[str, Any] = {"society": self.SOCIETY, "specialty": self.DEFAULT_SPECIALTY,
                               "event_type": event_type_for(title, shell.get("category") or "")}
        side = parse_sidebar(html)
        start = side.get("start_date") or shell.get("start_date")
        end = side.get("end_date") or start
        if start:
            out["start_date"] = start
            out["end_date"] = end if end and end >= start else start
        if side.get("start_time"):
            out["start_time"] = side["start_time"]
        place = split_place(side.get("place") or shell.get("venue_raw") or "")
        out.update(place)
        if place.get("city"):
            out["event_format"] = "in_person"
        desc = pick_description(html)
        org = side.get("organiser_url")
        if org:
            out["organiser_url"] = org
            ok, why = check_url_safe(org)
            if not ok:
                logger.warning(f"EULAR: organiser link refused ({why}): {org}")
            elif self._is_eular_moodle(org) or self._hops < self.MAX_ORGANISER_HOPS:
                if not self._is_eular_moodle(org):
                    self._hops += 1
                time.sleep(self.REQUEST_GAP_S)
                verdict, _final, body, enc, status = fetch_validated(org, deadline=time.monotonic() + 30, max_bytes=2_000_000)
                ohtml = body.decode(enc or "utf-8", errors="replace") if verdict == "ok" and body else ""
                if verdict != "ok":
                    logger.warning(f"EULAR: organiser page not used (verdict={verdict}, status={status}): {org}")
                elif self._is_eular_moodle(org):
                    cost = moodle_cost(ohtml)
                    if cost and cost["amount"] > 0:
                        out["pricing_tiers"] = [{"tier_label": "Registration · Standard", "price_gbp": cost["amount"],
                                                 "currency": cost["currency"], "is_early_bird": False, "early_bird_deadline": None}]
                else:
                    cand = pick_description(ohtml, whole_page=True)
                    if cand and year_conflict(cand, start):
                        logger.warning(f"EULAR: organiser text names another year than {start[:4]}, template used: {org}")
                        cand = None
                    desc = desc or cand
                    tiers = offers_tiers(ohtml)
                    if not tiers and self._hops < self.MAX_ORGANISER_HOPS:
                        link = fee_link(ohtml, org)
                        if link and check_url_safe(link)[0]:
                            self._hops += 1
                            time.sleep(self.REQUEST_GAP_S)
                            v2, _f2, b2, e2, st2 = fetch_validated(link, deadline=time.monotonic() + 30, max_bytes=2_000_000)
                            if v2 == "ok" and b2:
                                tiers = offers_tiers(b2.decode(e2 or "utf-8", errors="replace"))
                            else:
                                logger.warning(f"EULAR: fees page not used (verdict={v2}, status={st2}): {link}")
                    if tiers:
                        out["pricing_tiers"] = tiers
        out["description"] = desc or facts_description(title, shell.get("category") or "", out.get("start_date"), out.get("end_date"), place)
        out["description_source"] = "page" if desc else "template"
        return out
