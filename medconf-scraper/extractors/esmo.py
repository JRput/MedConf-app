"""European Society for Medical Oncology — meeting calendar extractor.

Source 17. The /meeting-calendar page is a Nuxt SPA — no meeting URLs
in the initial HTML. Listing uses Playwright: navigate, wait, scroll,
enumerate anchors matching /meeting-calendar/<slug>.

Detail pages: the useful content (title, dates, venue, fee tables) IS
in the raw HTML but Nuxt serialises the payload as JSON, so tags
appear as literal '\\u003Ctd\\u003E' etc. We decode those escapes
before regex extraction.

Event type from title:
- "Congress" → conference
- "Course", "Preceptorship", "Workshop", "Webinar", "Academy" → workshop
- Default → workshop (most ESMO events are educational, not conferences)
"""

import re
import html as _html
from datetime import date
from typing import Dict, Any, Optional, Callable, List

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


LISTING_URL = "https://www.esmo.org/meeting-calendar"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Cities where ESMO commonly runs events, ordered by prevalence
ESMO_CITIES = (
    "Lugano", "Madrid", "Zurich", "Munich", "Singapore", "Barcelona",
    "Vienna", "Berlin", "Paris", "Milan", "Rome", "London", "Amsterdam",
    "Copenhagen", "Stockholm", "Geneva", "Basel", "Brussels", "Dublin",
    "Warsaw", "Prague", "Athens", "Lisbon", "Kuala Lumpur", "Tokyo",
    "Sydney", "Boston", "New York", "Chicago", "San Francisco",
    "Abu Dhabi", "Dubai", "Riyadh",
)


def _unescape_json_html(s: str) -> str:
    """Nuxt serialises HTML payloads with \\uXXXX escapes. Decode them so
    the tag content (fee tables, dates) becomes parseable."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)


def _strip_and_normalise(raw_html: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw_html)
    txt = _html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt


def _parse_esmo_date_range(text: str) -> tuple:
    """Parse '5 May 2026', '5 – 7 October 2026', '24 October 2026' shapes."""
    # Day1 - Day2 Month Year
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s*[-–]\s*(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+(\d{4})",
        text, re.I,
    )
    if m:
        d1, d2, mon_name, y = (int(m.group(1)), int(m.group(2)),
                                m.group(3).lower(), int(m.group(4)))
        mon = _MONTHS.get(mon_name)
        if mon:
            return (f"{y:04d}-{mon:02d}-{d1:02d}",
                    f"{y:04d}-{mon:02d}-{d2:02d}")
    # Day1 Month - Day2 Month Year (cross-month)
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s*[-–]\s*"
        r"(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+(\d{4})",
        text, re.I,
    )
    if m:
        d1 = int(m.group(1)); mon1 = _MONTHS.get(m.group(2).lower())
        d2 = int(m.group(3)); mon2 = _MONTHS.get(m.group(4).lower())
        y = int(m.group(5))
        if mon1 and mon2:
            return (f"{y:04d}-{mon1:02d}-{d1:02d}",
                    f"{y:04d}-{mon2:02d}-{d2:02d}")
    # Single day
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+(\d{4})",
        text, re.I,
    )
    if m:
        d = int(m.group(1)); mon = _MONTHS.get(m.group(2).lower()); y = int(m.group(3))
        if mon:
            iso = f"{y:04d}-{mon:02d}-{d:02d}"
            return iso, iso
    return None, None


def _classify_event_type(title: str) -> str:
    tl = title.lower()
    if "congress" in tl and "workshop" not in tl:
        return "conference"
    return "workshop"


def _pricing_from_esmo_fee_table(decoded_html: str) -> List[dict]:
    """Extract fee tiers from ESMO's decoded fee table.

    Two layouts are seen:
    - Simple: "Early registration ... €70 ... €350" (member | non-member)
    - Multi-column: category rows with three prices (Early | Late | Full):
        ESMO Member          €310  €440  €590
        Developing Countries €150  €200  €295

    We detect the multi-column shape by finding groups of 2-4 €NNN amounts
    within a small span, then label each column using the timing header.
    """
    tiers: List[dict] = []
    seen: set = set()

    txt = re.sub(r"<[^>]+>", " ", decoded_html)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)

    # Determine COLUMN labels (early / late / full) if a header row exists
    hdr_m = re.search(
        r"(Early\s+registration).{0,150}?(Late\s+registration).{0,150}?"
        r"(Full\s+registration|Standard\s+registration|Onsite)",
        txt, re.I,
    )
    col_labels = ["Early registration", "Late registration",
                  "Full registration"] if hdr_m else None

    # Row-level category labels
    row_label_re = re.compile(
        r"(ESMO\s+Member(?:\s+Developing\s+Countries\*?)?(?:\s+in\s+Training\*{0,3})?|"
        r"Members?\s+affiliated\s+to\s+[A-Z]+(?:\s+and\s+[A-Z]+)*\*{0,3}|"
        r"Non\s+ESMO\s+Members?|Non-Member|"
        r"Standard\s+rate|Regular\s+rate|"
        r"Patient\s+Advocates?|Course\s+fee|Registration\s+fee|"
        r"Onsite)",
        re.I,
    )

    # For each row-label match, look forward up to ~200 chars to find € amounts.
    for lm in row_label_re.finditer(txt):
        label = re.sub(r"\s+", " ", lm.group(1)).strip()
        window = txt[lm.end(): lm.end() + 250]
        prices_in_window = re.findall(r"€\s?(\d+(?:\.\d{1,2})?)", window)
        if not prices_in_window:
            continue
        # Limit to first 4 prices (avoid slurping subsequent-row prices)
        for idx, p in enumerate(prices_in_window[:4]):
            try:
                price = float(p)
            except ValueError:
                continue
            if not (10 <= price <= 20000):
                continue
            if col_labels and idx < len(col_labels):
                full_label = f"{label} — {col_labels[idx]}"
            else:
                full_label = label
            full_label = full_label.strip()[:200]
            key = (full_label.lower(), price)
            if key in seen:
                continue
            seen.add(key)
            tiers.append({
                "tier_label": full_label,
                "price_gbp": price,
                "currency": "EUR",
                "is_early_bird": "early" in full_label.lower(),
                "early_bird_deadline": None,
            })

    # Fallback: simple label — € pattern (used for old-style two-column tables)
    if not tiers:
        tier_label_re = re.compile(
            r"(Early\s+registration(?:\s+extended)?|Late\s+registration|Onsite|"
            r"Standard\s+registration|Course\s+fee|Registration\s+fee)",
            re.I,
        )
        for m in re.finditer(r"€\s?(\d+(?:\.\d{1,2})?)", txt):
            price = float(m.group(1))
            if not (10 <= price <= 20000):
                continue
            window = txt[max(0, m.start() - 250):m.start()]
            matches = list(tier_label_re.finditer(window))
            if not matches:
                continue
            label = re.sub(r"\s+", " ", matches[-1].group(0)).strip()
            between = txt[matches[-1].end():m.start()]
            if between.count("€") >= 1:
                label = f"{label} — non-member"
            else:
                label = f"{label} — member"
            key = (label.lower(), price)
            if key in seen:
                continue
            seen.add(key)
            tiers.append({
                "tier_label": label[:200], "price_gbp": price,
                "currency": "EUR",
                "is_early_bird": "early" in label.lower(),
                "early_bird_deadline": None,
            })
    return tiers


def _extract_abstract_info(text: str) -> dict:
    """ESMO uses phrases like 'abstract submission deadline of 2 June 2026'
    or 'Late-breaking abstract submission deadline: DD MMM YYYY'."""
    out: dict = {}
    m = re.search(
        r"(?i)abstract\s+submission\s+deadline\s+(?:of|is|on|:)?\s*"
        r"(\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{4})",
        text,
    )
    if not m:
        m = re.search(
            r"(?i)(?:late\s*[-]\s*breaking\s+)?abstract\s+(?:submissions?|deadline)"
            r"[^0-9]{0,60}"
            r"(\d{1,2}(?:st|nd|rd|th)?\s+"
            r"(?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December)"
            r"\s+\d{4})",
            text,
        )
    if m:
        date_str = m.group(1)
        # Parse to ISO
        dm = re.match(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)\s+(\d{4})",
            date_str,
        )
        if dm:
            day, mon_name, y = int(dm.group(1)), dm.group(2).lower(), int(dm.group(3))
            mon = _MONTHS.get(mon_name)
            if mon:
                iso = f"{y:04d}-{mon:02d}-{day:02d}"
                out["abstract_deadline"] = iso
                today = date.today().isoformat()
                out["abstract_open"] = iso >= today
    return out


class ESMOExtractor(BaseExtractor):
    """European Society for Medical Oncology meeting calendar."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Nuxt SPA — need Playwright. Reuse the scraper's browser (launched
        # by AgentLoop) rather than starting a second sync_playwright, which
        # collides with the running one and raises "sync inside asyncio loop".
        br = getattr(self, "browser", None)
        if br is None or br.page is None:
            logger.warning("ESMO listing: no browser available; skipping")
            return None
        try:
            br.navigate(LISTING_URL)
            br.page.wait_for_timeout(10000)
            for _ in range(3):
                br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                br.page.wait_for_timeout(2000)
            cards = br.page.evaluate("""() => {
                const out = [];
                document.querySelectorAll('a[href*="/meeting-calendar/"]').forEach(a => {
                    const url = a.href;
                    const t = (a.innerText || '').trim();
                    if (t.length > 5 && !url.includes('?')) out.push({url, title: t});
                });
                return out;
            }""") or []
        except Exception as e:
            logger.warning(f"ESMO listing failed: {e}")
            return None

        # Slug patterns that are NAV, not real events
        NAV_SLUGS = ("past-meetings", "about-esmo-meetings",
                     "about-esmo-meetings-duplicated", "all-meetings",
                     "upcoming-meetings")
        seen = set()
        shells: List[Dict[str, Any]] = []
        for c in cards:
            url = c.get("url"); title = c.get("title")
            if not url or not title:
                continue
            url = url.split("#")[0].rstrip("/")
            if url in seen or url == LISTING_URL.rstrip("/"):
                continue
            if "/meeting-calendar/" not in url:
                continue
            slug = url.rsplit("/", 1)[-1]
            if slug in NAV_SLUGS:
                continue
            seen.add(url)
            shells.append({
                "title": title,
                "booking_url": url,
                "source_url": url,
            })
        logger.info(f"ESMO: listed {len(shells)} meetings")
        return shells if shells else None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or shell.get("booking_url") or ""
        title = shell.get("title") or ""
        out: Dict[str, Any] = {}

        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception as e:
            logger.warning(f"ESMO detail fetch failed for {url}: {e}")
            return out

        # Decode the Nuxt JSON-escaped HTML so tags/text become readable
        decoded = _unescape_json_html(raw)

        # Title — prefer h1 if present, else keep listing title
        h1 = re.search(r"<h1[^>]*>([^<]{5,200})</h1>", decoded, re.I)
        if h1:
            t = _html.unescape(h1.group(1).strip())
            t = re.sub(r"\s+", " ", t)
            if 5 < len(t) < 200:
                out["conference_name"] = t
                title = t
        if "conference_name" not in out:
            out["conference_name"] = title

        # Text form for date/location/pricing extraction
        txt = _strip_and_normalise(decoded)

        # Dates
        start, end = _parse_esmo_date_range(txt)
        if start:
            out["start_date"] = start
            if end and end != start:
                out["end_date"] = end

        # Event type. Format detection is city-driven: if the title
        # names a city, the event is in-person there; if it says "webinar"
        # or "virtual", online. The word "online" anywhere in body text
        # is a false signal (ESMO site chrome mentions it broadly).
        out["event_type"] = _classify_event_type(title)

        # City extraction — title first (ESMO uses "Course Name: Munich" convention)
        title_city_m = re.search(
            r"(?::\s+|\s+[–—]\s+|\s+in\s+)"
            r"("
            + "|".join(re.escape(c) for c in ESMO_CITIES)
            + r")"
            r"\s*(?:$|,|\s+\d{4})",
            title,
        )
        city = None
        venue = None
        if title_city_m:
            city = title_city_m.group(1)
        else:
            # Body-text fallback — several ESMO-specific patterns
            # Only high-confidence body patterns — the generic "in <city>,
            # <country>" catch-all was picking wrong cities from unrelated
            # passages (footer text, historical mentions).
            city_patterns = [
                # "held at [Venue Name] of Valencia"
                (r"(?:held\s+at|hosted\s+at)\s+the\s+"
                 r"([A-Z][A-Za-z ]+?)\s+of\s+"
                 r"(" + "|".join(re.escape(c) for c in ESMO_CITIES) + r")\b",
                 "venue_of_city"),
                # "held in <city>" / "venue: <city>" (strict anchor)
                (r"(?:held\s+in|takes?\s+place\s+in|venue\s+is[:\s]+|"
                 r"conference\s+venue[:\s]+)\s+"
                 r"(" + "|".join(re.escape(c) for c in ESMO_CITIES) + r")\b",
                 "held_in"),
            ]
            for pat, tag in city_patterns:
                m = re.search(pat, txt, re.I)
                if m:
                    if tag == "venue_of_city":
                        venue = f"{m.group(1)} of {m.group(2)}".strip()
                        city = m.group(2)
                    else:
                        city = m.group(1)
                    break

        # Format detection: title-declared cities OR "webinar/webcast" wins
        tl_title = title.lower()
        if "webinar" in tl_title or "webcast" in tl_title:
            out["event_format"] = "online"
        elif "virtual" in tl_title:
            out["event_format"] = "online"
        elif city:
            out["event_format"] = "in_person"
            out["city"] = city
            if venue:
                out["venue_name"] = venue
        else:
            # No city and no virtual marker in title. Check body carefully:
            # - "hybrid" or "in person or online" → hybrid
            # - "fully virtual", "delivered online" → online
            # - No location detail at all → default to online (safer than
            #   claiming in_person with no city)
            hybrid_m = re.search(
                r"(?:in\s+person\s+or\s+online|hybrid\s+(?:meeting|event|congress)|"
                r"in-person\s+and\s+online)",
                txt, re.I,
            )
            if hybrid_m:
                out["event_format"] = "hybrid"
            else:
                format_body = re.search(
                    r"(?:this\s+(?:meeting|course|event)\s+is\s+(?:virtual|online)|"
                    r"fully\s+virtual|virtual\s+event|delivered\s+online|"
                    r"course\s+is\s+delivered\s+entirely\s+online)",
                    txt, re.I,
                )
                if format_body:
                    out["event_format"] = "online"
                else:
                    # No city and no explicit format — safest default is
                    # online (ESMO webinars/courses default to online)
                    out["event_format"] = "online"

        # Pricing tiers from decoded fee table
        tiers = _pricing_from_esmo_fee_table(decoded)
        if tiers:
            out["pricing_tiers"] = tiers

        # Abstract submission dates (many ESMO conferences have them)
        abs_fields = _extract_abstract_info(txt)
        if abs_fields:
            out.update(abs_fields)

        # Specialty + society
        out["society"] = "ESMO"
        out["specialty"] = "Oncology"

        # Description — og:description first, else first meaningful paragraph
        meta = re.search(
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            decoded, re.I,
        )
        if meta:
            d = _html.unescape(meta.group(1)).strip()
            if 50 <= len(d) <= 700:
                out["description"] = d
        if "description" not in out:
            # Fallback: first paragraph mentioning the event's distinctive
            # tokens (e.g. "colorectal", "prostate", "webinar")
            title_words = {w for w in re.findall(r"[A-Za-z]{5,}", title.lower())
                           if w not in ("esmo", "cancer", "meeting", "conference",
                                        "webinar", "workshop", "course",
                                        "preceptorship", "academy")}
            for p in re.finditer(r"<p[^>]*>([^<]{80,700})</p>", decoded, re.I):
                d = _html.unescape(re.sub(r"\s+", " ", p.group(1))).strip()
                if 50 <= len(d) <= 700 and "cookie" not in d.lower():
                    if not title_words or any(w in d.lower() for w in title_words):
                        out["description"] = d
                        break

        return out
