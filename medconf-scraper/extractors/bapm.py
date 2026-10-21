"""BAPM (British Association of Perinatal Medicine) meetings and events: WordPress-family subclass, custom listing.

`bapm.org/pages/190-meetings-and-events` is a Hubble (White Fuse) CMS page, server-rendered, with one `div.teaser` per
upcoming event: `h2.title > a` (event page `/events/<slug>`), `.introduction` ("A two day in person event.", "An online
webinar.", "Join us in Northampton and Online.") and `.tags .mdi-calendar` with the START only ("3 Nov 2026 9:00am").
There is no pagination; past events live on `/events/past`. The list mixes BAPM-run meetings with external events
(Imperial's Neonatal Update, Eventbrite webinars, UCLH courses), so most `booking_url`s are the BAPM page and the
organiser site is stored as `organiser_url`.

Event pages are short: a prose description, then `Date: 23 - 26 November 2026` and `Location: In person - London`
lines (sometimes a full header "9 Mar 2027 9:00am to 10 Mar 2027 5:00pm"), and a "More details" / "Book now" link.
The end date comes from, in order: the header range, the `Date:` line, the duration words in the card intro ("two day").
For BAPM's own conference the "Book now" link is a CFS Events / EventsAir registration page whose fee list is public
server-rendered text (label, FULL, AMOUNT, GBP, 121.00, TOTAL); it is parsed here (second hop) for the tiers.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from logger import logger

from safe_fetch import check_url_safe, fetch_validated
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, classify_event_type, clip_venue, dedupe_consecutive,
                                find_dates, pick_event_dates)

_ROOT = "https://www.bapm.org"
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_CARD_RE = re.compile(r'(?is)<div class="teaser\b.*?(?=<div class="teaser\b|<footer|$)')
_LISTING_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})(?:\s+(\d{1,2}):(\d{2})\s*([ap]m))?", re.I)
_NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_DURATION_RE = re.compile(r"(?i)\b(one|two|three|four|five|six|\d)[\s-]day\b")

_UK_CITIES = {
    "London": "England", "Birmingham": "England", "Manchester": "England", "Liverpool": "England", "Leeds": "England",
    "Sheffield": "England", "Bristol": "England", "Newcastle": "England", "Nottingham": "England", "Leicester": "England",
    "Oxford": "England", "Cambridge": "England", "Southampton": "England", "Harrogate": "England", "Northampton": "England",
    "St Albans": "England", "Preston": "England", "Coventry": "England", "Kettering": "England", "Windsor": "England",
    "Darlington": "England", "York": "England", "Brighton": "England", "Bath": "England", "Exeter": "England",
    "Cardiff": "Wales", "Swansea": "Wales", "Edinburgh": "Scotland", "Glasgow": "Scotland", "Aberdeen": "Scotland",
    "Dundee": "Scotland", "Belfast": "Northern Ireland",
}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Listing HTML -> one dict per teaser (pure)."""
    out: List[Dict[str, Any]] = []
    for card in _CARD_RE.findall(html or ""):
        link = re.search(r'(?is)<h2 class="title">\s*<a href="(/events/[^"#?]+)"[^>]*>(.*?)</a>', card)
        when = re.search(r'(?is)mdi-calendar">(.*?)</div>', card)
        if not link or not when:
            continue
        m = _LISTING_DATE_RE.search(_txt(when.group(1)))
        if not m or m.group(2).lower() not in _MON:
            continue
        start = _iso(int(m.group(3)), _MON[m.group(2).lower()], int(m.group(1)))
        if not start:
            continue
        st = None
        if m.group(4):
            st = f"{int(m.group(4)) % 12 + (12 if m.group(6).lower() == 'pm' else 0):02d}:{m.group(5)}"
        intro = re.search(r'(?is)<div class="introduction">(.*?)</div>', card)
        title = _txt(re.sub(r"(?is)<span class=.image.*?</span></span>", "", link.group(2)))
        out.append({"title": title, "path": link.group(1), "start_date": start, "start_time": st, "intro": _txt(intro.group(1)) if intro else ""})
    return out


def end_from_intro(start: str, intro: str) -> Optional[str]:
    """"A two day in person event" starting 2026-11-03 -> 2026-11-04. None when no duration is stated."""
    m = _DURATION_RE.search(intro or "")
    if not m:
        return None
    n = _NUMWORDS.get(m.group(1).lower()) or int(m.group(1))
    return (date.fromisoformat(start) + timedelta(days=n - 1)).isoformat() if 1 < n <= 7 else None


def eventsair_tiers(html: str) -> List[Dict[str, Any]]:
    """CFS Events / EventsAir registration page -> tiers. Fee rows read "<label>", FULL, AMOUNT, GBP, 121.00, TOTAL."""
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html or "")
    lines = dedupe_consecutive(html_to_lines(body))
    text = " ".join(lines)
    deadline = None
    m = re.search(r"(?i)early bird deadline is[^.]{0,30}?(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", text)
    if m and m.group(2).lower() in _MON:
        deadline = _iso(int(m.group(3)), _MON[m.group(2).lower()], int(m.group(1)))
    tiers: List[Dict[str, Any]] = []
    section = None
    for i, ln in enumerate(lines):
        if re.match(r"(?i)^(?:in[- ]person|virtual|online)\s+registrations?$", ln):
            section = "In-person" if ln.lower().startswith("in") else "Virtual"
            continue
        if ln.upper() == "AMOUNT" and i >= 2 and i + 2 < len(lines) and re.match(r"^[A-Z]{3}$", lines[i + 1]):
            try:
                price = float(lines[i + 2].replace(",", ""))
            except ValueError:
                continue
            label = lines[i - 2] if lines[i - 1].upper() == "FULL" else lines[i - 1]
            early = bool(re.search(r"(?i)early[- ]bird", label))
            timing = "Early bird" if early else ("Late" if re.search(r"(?i)late[- ]bird", label) else None)
            cat = re.sub(r"(?i)\b(?:early|late)[- ]bird\s*:?\s*", "", label)
            cat = re.sub(r"(?i)\s*[-–]\s*(?:tuesday|wednesday|thursday|friday|monday|\d).*$", "", cat)
            cat = re.sub(r"(?i)\s+(?:in[- ]person|virtual)\b", "", cat).strip(" :-")
            tiers.append({"tier_label": " · ".join(x for x in (section, cat, timing) if x)[:120], "price_gbp": price,
                          "currency": lines[i + 1], "is_early_bird": early, "early_bird_deadline": deadline if early else None})
    tiers = [t for t in tiers if t["price_gbp"] > 0 or not re.search(r"(?i)quiz|dinner|drinks|social|gala", t["tier_label"])]   # free social items are not fees
    seen, out = set(), []
    for t in tiers:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


class BapmExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/pages/190-meetings-and-events"
    SOCIETY = "BAPM"
    DEFAULT_SPECIALTY = "Neonatology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(self.LISTING_URL)
        if not html:
            return None
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for r in parse_listing(html):
            end = end_from_intro(r["start_date"], r["intro"]) or r["start_date"]
            url = _ROOT + r["path"]
            if end < today or url in seen or re.search(r"(?i)cancel", r["title"]):
                continue
            seen.add(url)
            shells.append({"title": r["title"], "booking_url": url, "source_url": url, "start_date": r["start_date"], "end_date": end,
                           "start_time": r["start_time"], "venue_raw": None, "category": r["intro"] or None, "intro": r["intro"]})
        logger.info(f"BAPM: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    @staticmethod
    def _is_eventsair(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return host == "eventsair.com" or host.endswith(".eventsair.com")

    @staticmethod
    def _place(lines: List[str], intro: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """(venue, city, region, format) from the `Location:` line, a "will take place at" sentence and the card intro."""
        loc = next((m.group(1).strip() for ln in lines for m in [re.match(r"(?i)^location\s*:\s*(.+)$", ln)] if m), None)
        text = " ".join(lines)
        probe = f"{intro} {loc or ''}".lower()
        hybrid = bool(re.search(r"hybrid|and online|in person/hybrid|in[- ]person (?:and|&) online", probe))
        online = bool(re.search(r"\bonline\b|\bvirtual\b|\bwebinar\b", probe)) and not re.search(r"in[- ]person", probe) and not hybrid
        venue = None
        m = re.search(r"(?i)\b(?:will )?take place (?:at|in) (?:the )?([A-Z][^.]{2,80}?)(?:\.|,| on )", text)
        if m:
            venue = clip_venue(m.group(1).strip())
        city = None
        for c in _UK_CITIES:
            if re.search(rf"\b{c}\b", f"{loc or ''} {venue or ''}"):
                city = c
                break
        if not city and loc:
            plain = re.sub(r"(?i)^(?:in[- ]person|online|virtual|hybrid)\s*(?:[-\u2013:]|and\b)?\s*", "", loc).split(".")[0]
            plain = re.sub(r"(?i)\s+and\s+online$", "", plain).strip(" ,-\u2013")
            if plain and len(plain.split()) <= 3 and plain[0].isupper() and not re.search(r"(?i)\b(?:online|virtual|tbc|tba)\b", plain):
                city = plain
        if online:
            return None, None, None, "online"
        fmt = "hybrid" if hybrid else ("in_person" if (city or venue or "in person" in probe) else None)
        return venue, city, (_UK_CITIES.get(city) if city else None), fmt

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer|aside)\b.*?</\1\s*>", " ", html)))
        intro = shell.get("intro") or shell.get("category") or ""
        start = shell.get("start_date") or out.get("start_date")
        # ---- dates: header range > "Date:" line > card duration
        end = None
        head = next((l for l in lines[:6] if re.search(r"\d{4}.*\bto\b.*\d{4}", l)), None)
        if head:
            ds = find_dates(head)
            if len(ds) >= 2 and ds[0]["start"] == start:
                end = ds[-1]["end"]
        if not end:
            dl = next((m.group(1) for ln in lines for m in [re.match(r"(?i)^date\s*:\s*(.+)$", ln)] if m), None)
            if dl and start:
                if not re.search(r"\d{4}", dl):
                    dl = f"{dl} {start[:4]}"
                d = pick_event_dates(dl)
                if d and d[0] == start:
                    end = d[1]
        if not end:
            end = end_from_intro(start, intro) if start else None
        if start and end and end >= start:
            out["start_date"], out["end_date"] = start, end
        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]
        # ---- place + format
        for k in ("venue_name", "city", "region", "event_format"):
            out.pop(k, None)
        venue, city, region, fmt = self._place(lines, intro)
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        if region:
            out["region"] = region
        if fmt:
            out["event_format"] = fmt
        if not out.get("pricing_tiers"):                         # "ST5+ trainees and ANNPs = \u00a3500" rows under a Booking heading
            rows = [re.match(r"^(.{3,80}?)\s*=\s*\u00a3\s?(\d[\d,]*(?:\.\d{2})?)\s*$", l) for l in lines]
            tiers = [{"tier_label": f"Booking \u00b7 {m.group(1).strip()}"[:120], "price_gbp": float(m.group(2).replace(",", "")), "currency": "GBP",
                      "is_early_bird": False, "early_bird_deadline": None} for m in rows if m]
            if tiers:
                out["pricing_tiers"] = tiers
        # ---- type from the card intro ("webinar", "workshop", "course")
        out["event_type"] = classify_event_type(shell.get("title") or "", intro)
        # ---- organiser link + EventsAir fees (second hop)
        ext = []
        for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""", html):
            href = _html.unescape(m.group(1))
            label = _txt(m.group(2)).lower()
            if "bapm.org" in href or re.search(r"linkedin|twitter|facebook|whitefuse|instagram|youtube|amazonaws", href):
                continue
            if re.search(r"more details|book now|register|book online|tickets", label):
                ext.append((label, href))
        if ext:
            out["organiser_url"] = next((h for l, h in ext if "more details" in l), ext[0][1])
            reg = next((h for l, h in ext if self._is_eventsair(h) and h.rstrip("/").endswith("registrations")), None)
            if reg:
                ok, why = check_url_safe(reg)
                if not ok:
                    logger.warning(f"BAPM: registration link refused ({why}): {reg}")
                    reg = None
            if reg and not out.get("pricing_tiers"):
                time.sleep(self.REQUEST_GAP_S)
                verdict, _final, body, enc, status = fetch_validated(reg, deadline=time.monotonic() + 30, max_bytes=2_000_000)
                if verdict != "ok" or not body:
                    logger.warning(f"BAPM: registration page not used (verdict={verdict}, status={status}): {reg}")
                page_html = body.decode(enc or "utf-8", errors="replace") if verdict == "ok" and body else None
                tiers = eventsair_tiers(page_html) if page_html else []
                if tiers:
                    out["pricing_tiers"] = tiers
        return out
