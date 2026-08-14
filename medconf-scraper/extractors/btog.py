"""British Thoracic Oncology Group — events extractor.

Listing strategy:
  BTOG's /events/ page has two anchored sections: `#future` and `#past`.
  We slice the HTML between them and grab btog.org anchor links (each
  event has its own WordPress-style URL like /25th-btog-annual-conference-2027/).
  No Tribe API here (returns 404).

Detail strategy:
  Each event page is a WordPress page. Structured fields we extract:
    - Title from H1
    - Dates from UK-format strings ("3rd-5th March 2027")
    - Fees inline via £NNN patterns with adjacent tier-label words
    - Description = first paragraph after title
    - Venue: mostly Sheffield (annual conference) or online (webinars);
      detect "webinar/webcast" in title/URL → online

Type classification:
  - "annual conference" in title → conference, is_flagship=true
  - "webinar" or "webcast" in title → workshop, online
  - "trials meeting" or generic → workshop
"""

import re
import html as _html
from datetime import date
from typing import Dict, Any, Optional, Callable, List

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger


LISTING_URL = "https://www.btog.org/events/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


def _parse_uk_date_range(text: str, hint_year: Optional[int] = None) -> tuple:
    """Parse "3rd-5th March 2027" or "3rd to 5th March 2027" → (start_iso, end_iso)."""
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:[-–]|to)\s*(?:[A-Za-z]+\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})",
        text, re.I,
    )
    if m:
        d1, d2, mon, y = int(m.group(1)), int(m.group(2)), _MONTHS[m.group(3).lower()], int(m.group(4))
        return f"{y:04d}-{mon:02d}-{d1:02d}", f"{y:04d}-{mon:02d}-{d2:02d}"
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})",
        text, re.I,
    )
    if m:
        d, mon, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        iso = f"{y:04d}-{mon:02d}-{d:02d}"
        return iso, iso
    return None, None


def _classify_event_type(title: str, url: str) -> str:
    t = (title + " " + url).lower()
    if "annual conference" in t or "annual congress" in t:
        return "conference"
    if "webinar" in t or "webcast" in t or "webinar" in url:
        return "workshop"
    if "trials meeting" in t or "trial meeting" in t:
        return "workshop"
    return "workshop"


def _detect_format(title: str, body_text: str) -> str:
    t = (title + " " + body_text[:2000]).lower()
    if "webinar" in t or "webcast" in t or "online only" in t:
        return "online"
    if "sheffield" in t or "in-person" in t or "in person" in t:
        return "in_person"
    return "in_person"


def _extract_pricing(text: str) -> List[dict]:
    """BTOG puts fees inline: '... £330 Full rate for Drs ... £600 Per day
    charge £220 ...'. We match preceding label words up to 3 words back.

    Explicitly reject no-show/penalty fees ("charged a fee of £75 to cover
    the cost of your place if you do not attend") which are penalties,
    not registration prices.
    """
    tiers: List[dict] = []
    seen = set()

    # Reject: look at 80 chars BEFORE the price for penalty/no-show wording
    def is_penalty_context(text: str, price_start: int) -> bool:
        window = text[max(0, price_start - 120):price_start].lower()
        return any(k in window for k in (
            "do not attend", "if you do not", "no-show", "no show",
            "penalty", "will be charged a fee", "charged a fee of",
            "cover the cost", "cancellation fee",
        ))

    for m in re.finditer(
        r"((?:[A-Za-z][A-Za-z\-/]{2,30}\s+){1,8}?(?:rate|charge|day pass|charge|dinner|conference)|"
        r"(?:Non-profit|Sponsor|Agency|Consultant|Trainee|Student|Full))"
        r"[^£]{0,80}?£\s*(\d{1,4})",
        text, re.I,
    ):
        if is_penalty_context(text, m.start(2)):
            continue
        label = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
        try:
            price = float(m.group(2))
        except ValueError:
            continue
        if price <= 0 or price > 10000:
            continue
        if not label or len(label) < 4:
            continue
        key = (label.lower(), price)
        if key in seen:
            continue
        seen.add(key)
        tiers.append({
            "tier_label": label, "price_gbp": price, "currency": "GBP",
            "is_early_bird": "early" in label.lower(),
            "early_bird_deadline": None,
        })
    return tiers


def _parse_uk_date_to_iso(text: str) -> Optional[str]:
    """Parse "Monday 7th December 2026" → "2026-12-07"."""
    m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})",
        text, re.I,
    )
    if not m:
        return None
    d, mon_name, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    mon = _MONTHS.get(mon_name)
    if not mon or not (1 <= d <= 31):
        return None
    return f"{y:04d}-{mon:02d}-{d:02d}"


def _extract_abstract_info(text: str) -> dict:
    """Extract abstract submission dates from BTOG-style text:
       'Abstract Submission Opens Tuesday 1st September 2026
        Abstract submission closes: Monday 7th December 2026 23:59 GMT
        Abstract notification: Monday 11th January 2027'
    Returns dict of fields to patch: abstract_open, abstract_deadline,
    abstract_deadline_note."""
    from datetime import date as _date
    out: dict = {}

    # Find deadline (closes / closing / submission deadline)
    close_m = re.search(
        r"(?i)abstract\s+(?:submissions?\s+)?"
        r"(?:closes?|closing|deadline|submission\s+closes?)[:\s]+"
        r"(?:[A-Za-z]+day\s+)?"
        r"(\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{4})",
        text,
    )
    deadline_iso: Optional[str] = None
    if close_m:
        deadline_iso = _parse_uk_date_to_iso(close_m.group(1))
        if deadline_iso:
            out["abstract_deadline"] = deadline_iso

    # Find opening date
    open_m = re.search(
        r"(?i)abstract\s+submission\s+opens?[:\s]+"
        r"(?:[A-Za-z]+day\s+)?"
        r"(\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{4})",
        text,
    )
    open_iso: Optional[str] = None
    if open_m:
        open_iso = _parse_uk_date_to_iso(open_m.group(1))

    # Compute abstract_open based on today vs open/deadline
    today = _date.today().isoformat()
    if deadline_iso:
        if deadline_iso < today:
            out["abstract_open"] = False
        else:
            # Deadline is future — abstract is/will be open
            out["abstract_open"] = True
            if open_iso and open_iso > today:
                # Not open yet but will be — surface via note
                out["abstract_deadline_note"] = (
                    f"Opens {open_m.group(1) if open_m else open_iso}"
                )
    elif open_iso and open_iso <= today:
        out["abstract_open"] = True
    return out


def _extract_og_image(html: str) -> Optional[str]:
    """Parse Open Graph image URL from HTML head, with sensible fallbacks
    for sites that don't use OG meta tags (BTOG is one)."""
    m = re.search(
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
        html, re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"',
        html, re.I,
    )
    if m:
        return m.group(1)
    # Fallback: first prominent content <img> that isn't a logo / icon /
    # tracking pixel. Prefer any image whose URL mentions BTOG /
    # conference / banner / hero — those are typically the event artwork.
    prefer_re = re.compile(r"btog|conference|banner|hero|event", re.I)
    reject_re = re.compile(r"logo|icon|favicon|\.svg$|thumbnail|small|avatar|wp-includes", re.I)
    prefer: Optional[str] = None
    fallback: Optional[str] = None
    for m in re.finditer(r'<img[^>]+src="(https?://[^"]+\.(?:png|jpg|jpeg))"', html, re.I):
        src = m.group(1)
        if reject_re.search(src):
            continue
        if prefer_re.search(src) and not prefer:
            prefer = src
        elif not fallback:
            fallback = src
        if prefer:
            break
    return prefer or fallback


class BTOGExtractor(BaseExtractor):
    """British Thoracic Oncology Group."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # BTOG's WordPress host was intermittently slow (30-60s to
        # respond) during 2026-08-10 and 2026-08-14 scrape windows,
        # causing back-to-back failures. Widened timeout + added a
        # single httpx retry before falling through to the browser.
        import time
        html: Optional[str] = None
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True,
                                  headers={"User-Agent": USER_AGENT}) as c:
                    r = c.get(LISTING_URL)
                    r.raise_for_status()
                    html = r.text
                    break
            except Exception as e:
                last_err = e
                logger.warning(
                    f"BTOG listing fetch attempt {attempt + 1}/3 failed: {e}"
                )
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
        if html is None:
            logger.warning(f"BTOG listing fetch failed after 3 attempts: {last_err}")
            return None

        # Slice future section between #future anchor and #past
        future_idx = max(html.lower().find('id="future"'), html.lower().find(">future<"))
        past_idx = html.lower().find('id="past"')
        if past_idx < 0:
            past_idx = html.lower().find(">past<")
        section = html[future_idx:past_idx] if 0 <= future_idx < past_idx else html

        seen = set()
        shells: List[Dict[str, Any]] = []
        for m in re.finditer(
            r'href="(https?://(?:www\.)?btog\.org/([a-z0-9\-]+)/?)"[^>]*>([^<]+)</a>',
            section, re.I,
        ):
            url, slug, text = m.group(1), m.group(2), m.group(3).strip()
            text = re.sub(r"\s+", " ", text)
            if url in seen or not text or len(text) < 8:
                continue
            # Skip nav-style links
            if any(bad in slug for bad in (
                "events", "annual-reports", "membership", "about",
                "contact", "resources", "publications", "trials",
                "help-shape", "podcast", "guidelines",
            )) and "conference" not in slug and "webinar" not in slug \
                and "trial" not in slug and "meeting" not in slug \
                and "update" not in slug:
                continue
            if slug.endswith("archive"):
                continue
            seen.add(url)
            shells.append({
                "title": text,
                "booking_url": url,
                "source_url": url,
            })
            if len(shells) >= 30:
                break
        logger.info(f"BTOG: listed {len(shells)} future events")
        return shells if shells else None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        title = shell.get("title") or ""
        url = shell.get("source_url") or shell.get("booking_url") or ""

        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                html = r.text
        except Exception as e:
            logger.warning(f"BTOG detail fetch failed for {url}: {e}")
            return out

        # H1 override title
        h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", html, re.I)
        if h1:
            clean_title = _html.unescape(re.sub(r"\s+", " ", h1.group(1)).strip())
            if 5 < len(clean_title) < 200:
                title = clean_title
                out["conference_name"] = title

        # ORDER MATTERS: unescape BEFORE whitespace normalization so
        # &nbsp; (→ \xa0) gets collapsed by \s+. Doing it after leaves
        # \xa0 embedded and breaks any regex that expects normal spaces
        # (e.g. "London\xa0Join BTOG" fails our venue-boundary lookahead).
        txt = re.sub(r"<[^>]+>", " ", html)
        txt = _html.unescape(txt)
        txt = re.sub(r"\s+", " ", txt)

        # Event type + format
        et = _classify_event_type(title, url)
        out["event_type"] = et
        out["event_format"] = _detect_format(title, txt)

        # Flagship — only the annual conference
        if et == "conference" and "annual conference" in title.lower():
            out["is_flagship"] = True

        # Dates
        start, end = _parse_uk_date_range(txt)
        if start:
            out["start_date"] = start
            if end and end != start:
                out["end_date"] = end

        # Description — first 2 paragraph-shaped sentences after the title
        desc_match = re.search(
            r"<p[^>]*>([^<]{80,700})</p>", html, re.I,
        )
        if desc_match:
            desc = _html.unescape(re.sub(r"\s+", " ", desc_match.group(1))).strip()
            if 50 <= len(desc) <= 700:
                out["description"] = desc

        # Venue detection — anchor to phrases that indicate THE event's location
        # (not incidental city mentions elsewhere in the programme). Look for
        # patterns like "held at the EICC Edinburgh", "hosted at Sheffield City
        # Hall", "at the ICC Birmingham". Falls back to online for webinars.
        # Capture generously (up to 150 chars) then trim at any common
        # English sentence-start word. Trying to enumerate every possible
        # terminator in a regex lookahead was fragile — "Join" wasn't in
        # the list and killed the match entirely. This capture-then-trim
        # is more robust and generalises to other sources.
        venue_m = re.search(
            r"(?i)(?:will\s+be\s+held\s+at|held\s+at|hosted\s+at|takes?\s+place\s+at|"
            r"located\s+at|venue[:\s]+is|conference\s+venue[:\s]+|"
            r"Venue[:\s]+)\s*"
            r"(?:the\s+)?([A-Z][A-Za-z0-9 &,\-'.]{4,150})",
            txt,
        )
        if venue_m:
            venue = venue_m.group(1).strip()
            # Trim at the first common sentence-start word or field label.
            # Case-sensitive because these are almost always capitalized
            # (start of a new sentence or a field label like "Date:").
            # Terminators fall into three groups:
            #   - Days of the week (introduce a date range: "from Wednesday 3rd")
            #   - Prepositions (introduce a date/time: "from", "on")
            #   - Common event-page sentence-start words
            #   - Field labels ("Date:", "Time:")
            #   - Event/society names appearing after the venue
            SENTENCE_STARTS = (
                " from ", " on ", " between ",
                " Monday", " Tuesday", " Wednesday", " Thursday",
                " Friday", " Saturday", " Sunday",
                " Join ", " Please ", " Note ", " Overview ", " Programme ",
                " Registration ", " Book ", " This ", " These ", " The day ",
                " For ", " Cost", " Fee", " Speaker", " Times:", " Time:",
                " Date:", " Address:", " Tel:", " Email:", " Contact",
                " Free ", " Online ", " In-person ", " Poster ", " Format",
                " Sponsor", " CPD", " Abstract", " BTOG ",
            )
            for stop in SENTENCE_STARTS:
                idx = venue.find(stop)
                if idx > 4:
                    venue = venue[:idx]
                    break
            venue = venue.strip().rstrip(",.-")
            if 4 < len(venue) < 200:
                out["venue_name"] = venue
                # Extract city from the venue string itself
                for city in ("Edinburgh", "London", "Sheffield", "Manchester",
                             "Birmingham", "Belfast", "Glasgow", "Cardiff",
                             "Liverpool", "Bristol", "Leeds", "Newcastle"):
                    if city.lower() in venue.lower():
                        out["city"] = city
                        break
        if not out.get("city") and out.get("event_format") != "online":
            # Fallback: only use city name if it appears WITH a venue-anchor keyword
            for city in ("Edinburgh", "Sheffield", "Manchester", "Birmingham",
                         "Belfast", "Glasgow", "Cardiff", "Liverpool",
                         "Bristol", "Leeds", "Newcastle", "London"):
                if re.search(
                    rf"(?:held\s+at|at\s+the\s+[A-Z][^.]{{0,50}}?{re.escape(city)}|"
                    rf"in\s+{re.escape(city)}\b)",
                    txt, re.I,
                ):
                    out["city"] = city
                    break

        # Pricing (inline)
        tiers = _extract_pricing(txt)
        if tiers:
            out["pricing_tiers"] = tiers

        # Society + specialty. BTOG = British Thoracic Oncology Group —
        # every event is oncology-focused. classify_specialty defaults
        # unknown titles to "General Practice" which is wrong here, so
        # force Oncology for this source.
        out["society"] = "BTOG"
        out["specialty"] = "Oncology"

        # Note: image_url extraction removed — the conferences schema
        # doesn't currently have an image column. Add one when the
        # frontend wants event artwork; the _extract_og_image helper
        # still exists and can be wired back in trivially.

        # Abstract status — extract opening + closing dates from BTOG-style
        # "Abstract Submission Opens X / Abstract submission closes: Y / GMT"
        # patterns. Falls back to explicit open/closed wording elsewhere.
        abstract_fields = _extract_abstract_info(txt)
        if abstract_fields:
            out.update(abstract_fields)
        elif "abstract" in txt.lower():
            tl = txt.lower()
            if re.search(r"submissions?\s+(?:are\s+)?(?:now\s+)?closed", tl):
                out["abstract_open"] = False
            elif re.search(r"submissions?\s+(?:are\s+)?(?:now\s+)?open", tl):
                out["abstract_open"] = True

        return out
