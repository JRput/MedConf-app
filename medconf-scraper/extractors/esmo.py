"""European Society for Medical Oncology — meeting calendar extractor.

Source 17. Rewritten to use ESMO's Kontent CMS REST API for all
structured fields (city, venue, country, virtual flag, dates,
abstract deadlines, description). Falls back to HTML for the fee
table (Kontent's registration_fees is rich text that varies wildly
between events; regex-scraping the decoded page HTML is more reliable).

Kontent endpoint:
  https://kontent.cdn.aws.esmo.org/rest/items?system.type=meeting
  &limit=2000&elements=<field-list>

url_slug field on each Kontent item maps 1:1 to the URL path
(/meeting-calendar/<url_slug>), so we can match our shell rows.
"""

from __future__ import annotations
import re
import html as _html
from datetime import date
from typing import Dict, Any, Optional, Callable, List

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


LISTING_URL = "https://www.esmo.org/meeting-calendar"
KONTENT_API = "https://kontent.cdn.aws.esmo.org/rest/items"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_KONTENT_FIELDS = ",".join([
    "title", "url", "url_slug", "city", "venue", "country", "virtual",
    "start", "end", "abstracts_deadline", "application_deadline",
    "early_registration_deadline", "late_registration_deadline",
    "full_registration_deadline", "lba_deadline",
    "meeting_type", "registration_fees", "short_description",
])


def _fetch_kontent_by_slugs(slugs: set) -> dict:
    """Return {url_slug: kontent_item_elements} for all matching meetings."""
    try:
        with httpx.Client(timeout=60) as c:
            r = c.get(
                KONTENT_API,
                params={
                    "limit": "2000",
                    "system.type": "meeting",
                    "elements": _KONTENT_FIELDS,
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"ESMO Kontent fetch failed: {e}")
        return {}
    out: dict = {}
    for item in data.get("items", []):
        el = item.get("elements", {})
        slug = ((el.get("url_slug") or {}).get("value")
                or (el.get("url") or {}).get("value") or "")
        if slug in slugs:
            out[slug] = el
    return out


def _strip_html_to_text(s: str) -> str:
    """Kontent stores rich-text values with HTML tags; strip them."""
    if not s:
        return ""
    t = re.sub(r"<[^>]+>", " ", s)
    t = _html.unescape(t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _iso_from_kontent_date(v: Optional[str]) -> Optional[str]:
    """Kontent dates come as '2026-09-19T22:00:00Z'. Return YYYY-MM-DD."""
    if not v:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    return m.group(0) if m else None


def _parse_city(raw: Optional[str]) -> Optional[str]:
    """Kontent's city field is free text: 'Sydney, NSW', 'Lugano', 'Munich'.
    Take the first comma-separated segment."""
    if not raw:
        return None
    city = raw.split(",")[0].strip()
    if not city or city.lower() in ("virtual", "online", "tbc", "tbd", "n/a"):
        return None
    return city


def _classify_event_type(title: str, meeting_type_kontent: list) -> str:
    tl = title.lower()
    mt_names = [m.get("name", "").lower() for m in (meeting_type_kontent or [])]
    if any("congress" in n or "symposium" in n for n in mt_names):
        return "conference"
    if "congress" in tl:
        return "conference"
    return "workshop"


def _pricing_from_esmo_fee_table(decoded_html: str) -> List[dict]:
    """Extract fee tiers from ESMO's decoded fee table.

    Two layouts:
    - Simple: "Early registration ... €70 ... €350" (member | non-member)
    - Multi-column: category rows with 2-4 prices per row (Early | Late | Full)

    We detect the column layout by finding a header row that lists two or
    three registration-timing keywords, then decompose each category row.
    """
    tiers: List[dict] = []
    seen: set = set()

    txt = re.sub(r"<[^>]+>", " ", decoded_html)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)

    hdr_m = re.search(
        r"(Early\s+registration).{0,150}?(Late\s+registration).{0,150}?"
        r"(Full\s+registration|Standard\s+registration|Onsite)",
        txt, re.I,
    )
    col_labels = ["Early registration", "Late registration",
                  "Full registration"] if hdr_m else None

    row_label_re = re.compile(
        r"(ESMO\s+Member(?:\s+Developing\s+Countries\*?)?(?:\s+in\s+Training\*{0,3})?|"
        r"Members?\s+affiliated\s+to\s+[A-Z]+(?:[/\-\s]+[A-Z]+)*\*{0,3}|"
        r"Non\s+ESMO\s+Members?|Non-Member|"
        r"Standard\s+rate|Regular\s+rate|"
        r"Patient\s+Advocates?|Course\s+fee|Registration\s+fee|Onsite)",
        re.I,
    )

    for lm in row_label_re.finditer(txt):
        label = re.sub(r"\s+", " ", lm.group(1)).strip()
        window = txt[lm.end(): lm.end() + 250]
        prices_in_window = re.findall(r"€\s?(\d+(?:\.\d{1,2})?)", window)
        if not prices_in_window:
            continue
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
                "tier_label": full_label, "price_gbp": price,
                "currency": "EUR",
                "is_early_bird": "early" in full_label.lower(),
                "early_bird_deadline": None,
            })

    if not tiers:
        # Old-style two-column table fallback
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
            label = f"{label} — {'non-member' if between.count('€') >= 1 else 'member'}"
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


def _unescape_json_html(s: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)


def _extract_venue_from_paragraphs(rendered_text: str) -> Optional[str]:
    """Look for a paragraph containing 'will take place at the <Venue>' or
    'will be held at the <Venue>'. Also handles ESMO venue-subpage layout
    where the venue name stands on its own as a paragraph followed by
    a street address on the next line.

    The venue extraction is case-sensitive on the FIRST character of the
    capture (must be a REAL uppercase letter — venue names are capitalised
    proper nouns like "ICM-International Congress Center"). This prevents
    matches on lowercase phrases like "the heart of Europe" (case-
    insensitive `re.I` would otherwise let `[A-Z]` match lowercase 'h').
    """
    paragraphs = [p.strip() for p in rendered_text.split("\n\n") if p.strip()]

    # Strategy 1: find a full-sentence venue paragraph
    # "The <event> will take place at the <Venue> in <City>"
    for p in paragraphs:
        if p.count("\n") > 4:
            continue
        m = re.search(
            r"(?:will\s+take\s+place\s+at|will\s+be\s+held\s+at|"
            r"is\s+hosted\s+at|hosted\s+at)\s+"
            r"the\s+"
            r"([A-Z][A-Za-z0-9 .,'&\-–—]{5,150})",
            p,
        )
        if not m:
            continue
        v = m.group(1)
        for stop in (" in ", " from ", " on ", " which ", " where ",
                     " during ", " and ", ",", "\n"):
            idx = v.find(stop)
            if idx > 4:
                v = v[:idx]
                break
        # Also trim at street-address markers (street number after venue
        # name — e.g. "Suntec Singapore Convention & Exhibition Centre
        # 1 Raffles Boulevard" — cut at " <digit> " that starts an address)
        addr_m = re.search(r"\s+\d{1,4}\s+[A-Z]", v)
        if addr_m and addr_m.start() > 4:
            v = v[:addr_m.start()]
        # Trim at phone / postal markers
        v = re.split(
            r"\b(?:Tel[.:]|Phone[.:]|Fax[.:]|Email[:]|www\.|\+\d)",
            v,
        )[0]
        v = v.strip().rstrip(",.-;:")
        if 4 < len(v) < 120:
            return v

    # Strategy 2: ESMO venue-subpage often has "<Venue Name>\n<street>\n<city postcode>"
    # as a standalone paragraph (paragraph 1 in venue subpage tests).
    # The first line of such a paragraph, if it starts with capitalised
    # words and contains "Centre"/"Center"/"Convention"/"Hotel"/"Palace"
    # etc, is the venue name.
    venue_keyword_re = re.compile(
        r"(Centre|Center|Convention|Congress|Hotel|Palace|Building|"
        r"Hospital|Institute|Auditorium|Complex|Ballroom|Arena|Hall|Plaza|"
        r"Casino|Cinema|Villa|Chateau|Novotel|Marriott|Hilton|Sheraton|"
        r"Radisson)\b",
        re.I,
    )
    for p in paragraphs:
        if p.count("\n") > 4 or p.count("\n") < 1:
            continue
        first_line = p.split("\n")[0].strip()
        if not first_line:
            continue
        # Must start with capital letter and contain a venue keyword
        if not re.match(r"^[A-Z]", first_line):
            continue
        if not venue_keyword_re.search(first_line):
            continue
        # Cut at phone/postal/HTML markers
        cleaned = re.split(
            r"\b(?:Tel[.:]|Phone[.:]|Fax[.:]|Email[:]|www\.|\+\d)",
            first_line,
        )[0].strip()
        # Also cut at street number (e.g. "Suntec ... Centre 1 Raffles Blvd")
        addr_m = re.search(r"\s+\d{1,4}\s+[A-Z]", cleaned)
        if addr_m and addr_m.start() > 4:
            cleaned = cleaned[:addr_m.start()]
        cleaned = cleaned.rstrip(",.-;:")
        if 4 < len(cleaned) < 120:
            return cleaned
    return None


def _extract_description_from_paragraphs(
    rendered_text: str, title_tokens: set,
) -> Optional[str]:
    """Pick the best paragraph as the event description.

    Preferred order:
      1. A paragraph with a title-token match (most event-specific)
      2. A paragraph mentioning "congress", "meeting", "course",
         "workshop" (event-shaped generic descriptions)
      3. Longest surviving paragraph
    """
    paragraphs = [p.strip() for p in rendered_text.split("\n\n") if p.strip()]
    title_match: List[str] = []
    event_intro: List[str] = []
    EVENT_KEYWORDS = ("congress", "meeting", "course", "workshop",
                       "symposium", "preceptorship", "academy", "webinar")
    # Admin / logistical paragraphs to reject — these appear across many
    # ESMO event pages and cannot serve as a description of the event.
    REJECT_PHRASES = (
        "oncologypro", "daily reporter", "no results found",
        "meeting calendar", "home>meeting calendar", "cookie",
        "javascript", "sign in", "log in", "©", "esmo.org", "back to",
        "search",
        # Admin / registration / logistics
        "in addition to", "travel grant", "travel award",
        "hotel accommodation", "visa cost", "hotel booking",
        "housing agency", "official housing",
        "registration is now", "registration fee", "how to register",
        "how to submit", "abstract submission",
        "getting there", "how to reach", "public transport",
        "transportation", "airport is",
        "photography policy", "code of conduct", "terms and conditions",
        "privacy policy",
    )
    for p in paragraphs:
        if p.count("\n") > 3:
            continue
        pl = p.lower()
        if any(bad in pl for bad in REJECT_PHRASES):
            continue
        if not (80 <= len(p) <= 700):
            continue
        if title_tokens and any(t in pl for t in title_tokens):
            title_match.append(p)
        elif any(k in pl for k in EVENT_KEYWORDS):
            event_intro.append(p)
    pool = title_match or event_intro
    if pool:
        pool.sort(key=len, reverse=True)
        return pool[0]
    return None


class ESMOExtractor(BaseExtractor):
    """European Society for Medical Oncology meeting calendar."""

    # Cache: url_slug -> kontent elements. Populated in list_shells_override
    # and re-used in extract_detail so we hit the API only once.
    _kontent_cache: dict = {}

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
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

            # Harvest cards from every pagination page. The listing renders
            # ~18 events per page and has numbered [aria-label="Page N"]
            # buttons at the bottom. Click each one in turn.
            all_cards: List[dict] = []
            page_num = 1
            while page_num <= 20:  # hard cap for safety
                # Harvest current page's meeting URLs
                cards = br.page.evaluate("""() => {
                    const out = [];
                    document.querySelectorAll('a[href*="/meeting-calendar/"]').forEach(a => {
                        const url = a.href;
                        const t = (a.innerText || '').trim();
                        if (t.length > 5 && !url.includes('?')) out.push({url, title: t});
                    });
                    return out;
                }""") or []
                all_cards.extend(cards)
                # Try to click the next-page button
                next_button_clicked = br.page.evaluate(
                    "(nextPage) => { "
                    "const btn = document.querySelector(`button[aria-label=\"Page ${nextPage}\"]`); "
                    "if (btn) { btn.scrollIntoView(); btn.click(); return true; } "
                    "return false; }",
                    page_num + 1,
                )
                if not next_button_clicked:
                    break
                # Wait for the new page to render
                br.page.wait_for_timeout(4000)
                for _ in range(2):
                    br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    br.page.wait_for_timeout(1500)
                page_num += 1
            logger.info(f"ESMO: walked {page_num} pagination page(s)")
            cards = all_cards
        except Exception as e:
            logger.warning(f"ESMO listing failed: {e}")
            return None

        NAV_SLUGS = ("past-meetings", "about-esmo-meetings",
                     "about-esmo-meetings-duplicated", "all-meetings",
                     "upcoming-meetings")
        seen = set()
        shells: List[Dict[str, Any]] = []
        for c in cards:
            url = (c.get("url") or "").split("#")[0].rstrip("/")
            title = c.get("title")
            if not url or not title:
                continue
            if url in seen or url == LISTING_URL.rstrip("/"):
                continue
            if "/meeting-calendar/" not in url:
                continue
            slug = url.rsplit("/", 1)[-1]
            if slug in NAV_SLUGS:
                continue
            seen.add(url)
            shells.append({"title": title, "booking_url": url,
                           "source_url": url, "slug": slug})

        # Batch-fetch Kontent data for all these slugs — one API call
        slug_set = {s["slug"] for s in shells}
        self._kontent_cache = _fetch_kontent_by_slugs(slug_set)
        logger.info(
            f"ESMO: listed {len(shells)} meetings; "
            f"Kontent matched {len(self._kontent_cache)}"
        )
        return shells if shells else None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or ""
        slug = shell.get("slug") or url.rsplit("/", 1)[-1]
        out: Dict[str, Any] = {}

        # 1. Fields from Kontent CMS (authoritative)
        kontent = self._kontent_cache.get(slug) if self._kontent_cache else None
        if not kontent:
            # Re-fetch just this slug if it wasn't in the batch (defensive)
            self._kontent_cache = _fetch_kontent_by_slugs({slug})
            kontent = self._kontent_cache.get(slug)

        if kontent:
            title_val = (kontent.get("title") or {}).get("value")
            if title_val and len(title_val.strip()) > 5:
                out["conference_name"] = title_val.strip()

            city_raw = (kontent.get("city") or {}).get("value")
            city = _parse_city(city_raw)

            # Kontent stores venue as HTML like:
            #   <p><a href="...">Suntec Singapore Convention Centre</a><br>
            #   1 Raffles Boulevard<br>Suntec City<br>Tel: +65 ...</p>
            # We want only the FIRST line (the venue name) — split on <br>
            # before stripping other tags.
            venue_raw = (kontent.get("venue") or {}).get("value", "")
            if venue_raw:
                # Split on <br> variants, take the first non-empty line
                lines = re.split(r"<br\s*/?>", venue_raw, flags=re.I)
                first_line = _strip_html_to_text(lines[0]) if lines else ""
                if first_line and len(first_line) >= 4 and first_line != " ":
                    # Trim at phone / postal / street number
                    v = re.split(
                        r"\b(?:Tel[.:]|Phone[.:]|Fax[.:]|Email[:]|www\.|\+\d)",
                        first_line,
                    )[0].strip()
                    addr_m = re.search(r"\s+\d{1,4}\s+[A-Z]", v)
                    if addr_m and addr_m.start() > 4:
                        v = v[:addr_m.start()]
                    v = v.strip().rstrip(",.-;:")
                    if 4 < len(v) < 120:
                        out["venue_name"] = v

            country_val = (kontent.get("country") or {}).get("value")
            country_name = None
            if isinstance(country_val, list) and country_val:
                country_name = country_val[0].get("name")

            virtual_val = (kontent.get("virtual") or {}).get("value")
            is_virtual = False
            if isinstance(virtual_val, list) and virtual_val:
                is_virtual = virtual_val[0].get("codename") == "yes"

            meeting_type_val = (kontent.get("meeting_type") or {}).get("value", [])

            # Format decision from Kontent
            if is_virtual and not city:
                out["event_format"] = "online"
            elif is_virtual and city:
                out["event_format"] = "hybrid"
                out["city"] = city
            elif city:
                out["event_format"] = "in_person"
                out["city"] = city
            else:
                # Kontent says not virtual, no city — genuinely undetermined
                # Default to online for safety (webinars, virtual courses)
                # UNLESS the meeting_type suggests otherwise
                mt_names = [m.get("name", "").lower() for m in meeting_type_val]
                if any("webinar" in n or "series" in n for n in mt_names):
                    out["event_format"] = "online"
                else:
                    out["event_format"] = "online"

            # Dates
            start_iso = _iso_from_kontent_date(
                (kontent.get("start") or {}).get("value"))
            end_iso = _iso_from_kontent_date(
                (kontent.get("end") or {}).get("value"))
            if start_iso:
                out["start_date"] = start_iso
            if end_iso:
                out["end_date"] = end_iso

            # Event type
            out["event_type"] = _classify_event_type(
                out.get("conference_name") or shell.get("title", ""),
                meeting_type_val,
            )

            # Abstract deadline
            abs_dl = _iso_from_kontent_date(
                (kontent.get("abstracts_deadline") or {}).get("value")
                or (kontent.get("lba_deadline") or {}).get("value"))
            if abs_dl:
                out["abstract_deadline"] = abs_dl
                today = date.today().isoformat()
                out["abstract_open"] = abs_dl >= today

            # Description — short_description (Kontent) is authoritative
            desc_raw = (kontent.get("short_description") or {}).get("value", "")
            desc_text = _strip_html_to_text(desc_raw)
            if desc_text and 50 <= len(desc_text) <= 700:
                out["description"] = desc_text

        # 2. Fetch HTML for fee table + venue + description.
        # The main page is JS-rendered so httpx alone misses the visible
        # description. We use httpx for the fee table (Nuxt payload) AND
        # Playwright for the rendered body text (description, venue link).
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception as e:
            logger.warning(f"ESMO detail fetch failed for {url}: {e}")
            raw = ""

        # Playwright-rendered body text — contains the visible description
        # AND any /venue sub-page link. Reuses scraper's shared browser.
        rendered_text = ""
        venue_subpage_url: Optional[str] = None
        br = getattr(self, "browser", None)
        if br is not None and br.page is not None:
            try:
                br.navigate(url)
                br.page.wait_for_timeout(8000)
                for _ in range(2):
                    br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    br.page.wait_for_timeout(1500)
                rendered_text = br.page.evaluate(
                    "() => document.body.innerText || ''"
                ) or ""
                # Look for a /venue sub-page link on this event
                venue_subpage_url = br.page.evaluate(
                    "(base) => { "
                    "const a = Array.from(document.querySelectorAll('a')) "
                    ".find(a => (a.href || '').startsWith(base) && "
                    "(a.href || '').toLowerCase().endsWith('/venue')); "
                    "return a ? a.href : null; }",
                    url,
                )
            except Exception as e:
                logger.warning(f"ESMO Playwright detail fetch failed: {e}")

        # If venue is still missing AND a /venue sub-page exists, fetch it
        if "venue_name" not in out and venue_subpage_url:
            try:
                if br is not None and br.page is not None:
                    br.navigate(venue_subpage_url)
                    br.page.wait_for_timeout(6000)
                    for _ in range(2):
                        br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        br.page.wait_for_timeout(1500)
                    venue_text = br.page.evaluate(
                        "() => document.body.innerText || ''"
                    ) or ""
                    v = _extract_venue_from_paragraphs(venue_text)
                    if v:
                        out["venue_name"] = v
            except Exception as e:
                logger.warning(f"ESMO venue-subpage fetch failed: {e}")

        # If venue STILL missing, look in the main event page's rendered text
        if "venue_name" not in out and rendered_text:
            v = _extract_venue_from_paragraphs(rendered_text)
            if v:
                out["venue_name"] = v

        if raw:
            decoded = _unescape_json_html(raw)
            tiers = _pricing_from_esmo_fee_table(decoded)
            if tiers:
                out["pricing_tiers"] = tiers

            # Venue fallback — Kontent's venue is often empty. Look for
            # "The course/meeting will be held at [Name] of/in [City]"
            # or "hosted at the [Name]" in decoded HTML.
            if "venue_name" not in out:
                # Capture generously then trim at first sentence-start word
                # (same pattern as BTOG). Avoids fragile lookahead alternation.
                venue_m = re.search(
                    r"(?:will\s+be\s+held\s+at|held\s+at|hosted\s+at)\s+the\s+"
                    r"([A-Z][A-Za-z0-9 .,'&\-]{5,150})",
                    decoded, re.I,
                )
                if venue_m:
                    v = venue_m.group(1)
                    for stop in (" from ", " on ", " between ", " which ",
                                 " where ", " it ", " and it", " and is ",
                                 " and the ", " which is",
                                 " Monday", " Tuesday", " Wednesday",
                                 " Thursday", " Friday", " Saturday",
                                 " Sunday", " for the ", " during ",
                                 " situated ", " located ", " Please ",
                                 " Registration ", " Date:", " Time:",
                                 "<", "\\n"):
                        idx = v.find(stop)
                        if idx > 4:
                            v = v[:idx]
                            break
                    v = _html.unescape(v).strip().rstrip(",.-;:")
                    v = re.sub(r"\s+", " ", v)
                    if 4 < len(v) < 200:
                        out["venue_name"] = v

            # Description fallback chain:
            # 1. Rendered body text (highest priority — real user-facing content)
            # 2. og:description meta tag
            # 3. Long <p> in raw HTML
            # 4. Synthetic template
            if "description" not in out and rendered_text:
                title_tokens = set(re.findall(
                    r"[a-z]{5,}",
                    (out.get("conference_name") or "").lower(),
                )) - {"esmo", "cancer", "meeting", "conference", "congress",
                       "webinar", "workshop", "course", "preceptorship",
                       "academy", "webcast", "advanced", "series",
                       "annual", "summit", "symposium"}
                d = _extract_description_from_paragraphs(rendered_text, title_tokens)
                if d:
                    out["description"] = d
            if "description" not in out:
                m = re.search(
                    r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
                    decoded, re.I,
                )
                if m:
                    d = _html.unescape(m.group(1)).strip()
                    if 50 <= len(d) <= 700:
                        out["description"] = d
            if "description" not in out:
                # Take the longest <p> paragraph on the page (excluding nav
                # boilerplate). Prefer paragraphs that mention title tokens;
                # fall back to longest general paragraph if none match.
                title_tokens = set(re.findall(
                    r"[a-z]{5,}",
                    (out.get("conference_name") or "").lower(),
                )) - {"esmo", "cancer", "meeting", "conference", "webinar",
                       "workshop", "course", "preceptorship", "academy",
                       "webcast", "advanced", "course", "series"}
                title_match_candidates: List[str] = []
                general_candidates: List[str] = []
                for p in re.finditer(r"<p[^>]*>([^<]{80,700})</p>", decoded, re.I):
                    d = _html.unescape(re.sub(r"\s+", " ", p.group(1))).strip()
                    if not (50 <= len(d) <= 700):
                        continue
                    dl = d.lower()
                    if any(bad in dl for bad in ("cookie", "javascript",
                                                   "sign in", "log in",
                                                   "register now", "©",
                                                   "esmo.org")):
                        continue
                    general_candidates.append(d)
                    if title_tokens and any(t in dl for t in title_tokens):
                        title_match_candidates.append(d)
                # Only use a general-candidate description if it has title
                # tokens (i.e. is actually about THIS event, not a page-wide
                # ambient article). Otherwise fall through to the synthetic
                # description below.
                if title_match_candidates:
                    title_match_candidates.sort(key=len, reverse=True)
                    out["description"] = title_match_candidates[0]

        # 3. Synthetic description as last resort — some ESMO pages have no
        # rendered description at all (preceptorships, courses). Build one
        # from the title + city + dates so users see something meaningful,
        # AND it always shares title tokens with the title (passes audit).
        if "description" not in out:
            title = out.get("conference_name") or shell.get("title") or ""
            city = out.get("city")
            fmt = out.get("event_format", "online")
            start = out.get("start_date")
            end = out.get("end_date")
            date_str = ""
            if start:
                if end and end != start:
                    date_str = f" running {start} to {end}"
                else:
                    date_str = f" on {start}"
            loc_str = ""
            if fmt == "online":
                loc_str = " Delivered online."
            elif city:
                loc_str = f" Held in {city}."
            out["description"] = (
                f"{title} is an ESMO educational meeting for oncology "
                f"professionals{date_str}.{loc_str} Registration and full "
                f"details on the ESMO meeting calendar."
            )[:700]

        # 3. Final safety net for required fields
        if "conference_name" not in out and shell.get("title"):
            out["conference_name"] = shell["title"]
        if "event_type" not in out:
            out["event_type"] = "workshop"
        if "event_format" not in out:
            out["event_format"] = "online"

        # 4. Static classification
        out["society"] = "ESMO"
        out["specialty"] = "Oncology"

        return out
