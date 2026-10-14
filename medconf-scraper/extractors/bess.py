"""BESS (British Elbow & Shoulder Society) courses and events: WordPress family subclass, browser-first listing.

`bess.ac.uk/courses-and-events/` is a WordPress page built with the CoBlocks "Events" carousel (JS-rendered
swiper). Each slide is `div.wp-block-coblocks-event-item` with day / month / year spans, a title span, a
description span (usually holding the link to the event page), a time and a location. There are two carousels:
"BESS Courses and Events" and "Other Courses and Events" (third-party meetings, e.g. SECEC, ICSES, BOA). The
page makes no API call for them (the posts REST endpoint holds news, not events), so Phase A reads the rendered
slides.

Slides: day "13-14", "30-2" (range crossing months, month span "June – July"), month, year. A slide without a link
(BESS 2027 Manchester, "Coming soon!") has no page of its own and gets a `<listing>#<slug>` URL; its detail comes
from the slide. Elevate and the Elbow Updates Symposium sell places through a WooCommerce product page
(`/product/<slug>/`, linked from the event page): the price and an "Out of stock" flag are read from there.
Many slides are past (the carousel keeps this year's), so only slides ending today or later are kept.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, classify_event_type, split_location

_LISTING = "https://bess.ac.uk/courses-and-events/"
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_ITEM_RE = re.compile(r'(?is)<div class="wp-block-coblocks-event-item\b.*?(?=<div class="wp-block-coblocks-event-item\b|<button class="wp-coblocks-events-nav|</section>|$)')
_PRODUCT_RE = re.compile(r'href="(https://bess\.ac\.uk/product/[^"#?]+/?)"')


def _field(item: str, cls: str) -> str:
    m = re.search(r'(?is)<span class="wp-block-coblocks-events__%s"[^>]*>(.*?)</span>' % cls, item)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""


def _month(name: str) -> Optional[int]:
    n = name.strip().lower()
    for i, full in enumerate(_MONTHS, 1):
        if n.startswith(full[:3]):
            return i
    return None


def parse_slide_dates(day: str, month: str, year: str) -> Optional[tuple]:
    """'13-14' + 'October' + '2026' -> ('2026-10-13', '2026-10-14'); '30-2' + 'June – July' + '2027' -> ('2027-06-30', '2027-07-02')."""
    try:
        y = int(year)
        days = [int(x) for x in re.findall(r"\d+", day)]
        months = [_month(x) for x in re.split(r"\s*[–—-]\s*", month) if x.strip()]
        if not days or not months or None in months:
            return None
        d1, d2 = days[0], days[-1]
        m1, m2 = months[0], months[-1]
        return date(y, m1, d1).isoformat(), date(y + (1 if m2 < m1 else 0), m2, d2).isoformat()
    except (ValueError, TypeError):
        return None


def parse_slides(html: str) -> List[Dict[str, Any]]:
    """Rendered listing HTML -> one dict per slide. Pure."""
    out: List[Dict[str, Any]] = []
    for item in _ITEM_RE.findall(html or ""):
        title = _field(item, "title")
        dates = parse_slide_dates(_field(item, "day"), _field(item, "month"), _field(item, "year"))
        if not title or not dates:
            continue
        links = [h for h in re.findall(r'href="(https?://[^"]+)"', item) if "bess.ac.uk/wp-content" not in h]
        out.append({"title": title, "start": dates[0], "end": dates[1], "link": links[0].split("#")[0] if links else None,
                    "time": _field(item, "time"), "location": _field(item, "location"), "note": _field(item, "description")})
    return out


class BessExtractor(WordPressGenericExtractor):
    LISTING_URL = _LISTING
    SOCIETY = "BESS"
    DEFAULT_SPECIALTY = "Orthopaedics"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    def _listing_html(self) -> Optional[str]:
        browser = getattr(self, "browser", None)
        for attempt in range(3):
            try:
                if browser is not None:
                    browser.navigate(_LISTING)
                    try:
                        browser.page.wait_for_selector(".wp-block-coblocks-event-item", state="attached", timeout=15000)
                    except Exception:  # noqa: BLE001
                        pass
                    body = browser.page.content()
                else:
                    body = self._fetch(_LISTING)
                if body and "wp-block-coblocks-event-item" in body:
                    return body
            except Exception as e:  # noqa: BLE001
                logger.warning(f"BESS listing load {attempt + 1}/3 failed: {e}")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._listing_html()
        if not html:
            return None
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for s in parse_slides(html):
            if s["end"] < today or re.search(r"cancel", s["title"] + " " + s["note"], re.I):
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", s["title"].lower()).strip("-")[:60]
            url = s["link"] or f"{_LISTING}#{slug}"
            if url in seen:
                continue
            seen.add(url)
            st = re.search(r"(\d{1,2})[:.](\d{2})", s["time"])
            shells.append({"title": s["title"], "booking_url": url, "source_url": url, "start_date": s["start"], "end_date": s["end"],
                           "start_time": f"{int(st.group(1)):02d}:{st.group(2)}" if st else None,
                           "venue_raw": s["location"] or None, "category": None, "has_page": bool(s["link"]), "note": s["note"]})
        logger.info(f"BESS: {len(shells)} upcoming slides")
        return shells or None

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        if not shell.get("has_page"):
            return self._slide_only(shell)
        html = page.content() if page is not None else ""
        out = self.detail_from_html(html, shell, llm_call)
        out["start_date"], out["end_date"] = shell["start_date"], shell["end_date"]
        out["society"] = self.SOCIETY
        desc = re.sub(r"^\s*\d{1,2}(?:\s*[-\u2013]\s*\d{1,2})?\s+[A-Za-z]+\s+20\d\d\s*(?:[A-Z][A-Za-z]+(?:,\s*[A-Z][A-Za-z]+)*)?\s+(?=[A-Z][a-z]+ )", "", out.get("description") or "")
        if desc:
            out["description"] = desc
        out["event_type"] = self._event_type(shell["title"], desc)
        if (out.get("city") or out.get("venue_name")) and not out.get("region"):
            out["region"] = "United Kingdom"
        self._partner_page_extras(html, out)
        m = _PRODUCT_RE.search(html)
        if m and not out.get("pricing_tiers"):
            price, sold_out = self._product(m.group(1))
            if price is not None:
                out["pricing_tiers"] = [{"tier_label": "Registration · Course fee", "price_gbp": price, "currency": "GBP",
                                         "is_early_bird": False, "early_bird_deadline": None}]
            if sold_out:
                out["is_sold_out"] = True
        return out

    @staticmethod
    def _partner_page_extras(html: str, out: Dict[str, Any]) -> None:
        """Partner (ORUK) event pages: 'Location:' value, 'CPD / 5 credits (applied for)' and a ticket list of
        'Early bird - <category>' label lines each followed by '- \u00a370.00'. The family parser reads none of these."""
        lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer|header)\b.*?</\1>", " ", html))
        for i, ln in enumerate(lines[:-1]):
            if re.fullmatch(r"location\s*:?", ln, re.I) and not out.get("venue_name"):
                v = lines[i + 1].strip()
                if v and not re.match(r"(?i)see website|tbc|tba|online", v) and len(v) < 120:
                    out["venue_name"] = v
            if ln.strip().upper() == "CPD" and out.get("cpd_points") is None:
                m = re.match(r"^(\d+(?:\.\d+)?)\s+(?:CPD\s+)?(?:credits?|points?)\b(.*)$", lines[i + 1].strip(), re.I)
                if m:
                    out["cpd_points"] = float(m.group(1))
                    out["cpd_accredited"] = not re.search(r"applied for|pending|tbc", m.group(2), re.I)
        if out.get("pricing_tiers"):
            return
        start = next((i for i, l in enumerate(lines) if re.fullmatch(r"select ticket options", l.strip(), re.I)), None)
        if start is None:
            return
        tiers: List[Dict[str, Any]] = []
        for i in range(start + 1, len(lines) - 1):
            m = re.match(r"^[-\u2013]?\s*\u00a3\s*([\d,]+(?:\.\d\d)?)\s*$", lines[i].strip().replace("\xa0", " "))
            if not m:
                continue
            label = lines[i - 1].strip()
            if not label or re.fullmatch(r"\d{1,2}", label):
                continue
            early = bool(re.match(r"(?i)early bird\b", label))
            who = re.sub(r"(?i)^(?:early bird|standard|regular|late)\s*[-\u2013:]\s*", "", label).strip()
            when = "Early bird" if early else ("Standard" if re.match(r"(?i)(standard|regular)\b", label) else None)
            tiers.append({"tier_label": " \u00b7 ".join(x for x in ("Registration", who, when) if x),
                          "price_gbp": float(m.group(1).replace(",", "")), "currency": "GBP",
                          "is_early_bird": early, "early_bird_deadline": None})
        if tiers:
            out["pricing_tiers"] = tiers

    @staticmethod
    def _event_type(title: str, desc: str = "") -> str:
        if re.search(r"scientific meeting|congress|symposium|conference", title, re.I):
            return "conference"
        by_title = classify_event_type(title, "")
        if by_title != "conference":
            return by_title
        return "course" if re.search(r"\bcourse\b|cadaver", desc, re.I) else "conference"

    def _slide_only(self, shell: Dict[str, Any]) -> Dict[str, Any]:
        v, c, k = split_location(shell.get("venue_raw"))
        out: Dict[str, Any] = {"society": self.SOCIETY, "start_date": shell["start_date"], "end_date": shell["end_date"],
                               "event_type": self._event_type(shell["title"]), "specialty": self.DEFAULT_SPECIALTY,
                               "pricing_tiers": []}
        if v:
            out["venue_name"] = v
        if c:
            out["city"] = c
        if v or c:
            out["event_format"] = "in_person"
            out["region"] = k or "United Kingdom"
        note = shell.get("note") or ""
        out["description"] = f"{shell['title']}. " + (f"{note}" if note and not re.fullmatch(r"coming soon!?", note, re.I) else "Details have not been published yet.")
        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]
        return out

    def _product(self, url: str):
        """WooCommerce product page -> (price in GBP or None, out-of-stock flag). One extra page load."""
        browser = getattr(self, "browser", None)
        try:
            html = fetch_html(url, browser=browser) or ""     # httpx first: leaves the browser on the event page
        except Exception as e:  # noqa: BLE001
            logger.warning(f"BESS product page failed {url}: {e}")
            return None, False
        lines = html_to_lines(re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1>", " ", html))
        price = None
        for i, ln in enumerate(lines[:60]):
            m = re.match(r"^£\s*([\d,]+(?:\.\d\d)?)$", ln.strip())
            if m:
                price = float(m.group(1).replace(",", ""))
                break
            if ln.strip() == "£" and i + 1 < len(lines) and re.match(r"^[\d,]+(?:\.\d\d)?$", lines[i + 1].strip()):
                price = float(lines[i + 1].replace(",", ""))
                break
        return price, any(re.fullmatch(r"out of stock", l.strip(), re.I) for l in lines[:80])
