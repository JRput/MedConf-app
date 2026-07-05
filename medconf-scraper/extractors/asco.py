"""American Society of Clinical Oncology — extractors.

Two source variants share this module:
- ASCOAnnualExtractor (source 15): the /annual-meeting flagship subsite.
  Currently shows 2027 Save the Date content. One conference row.
- ASCOMeetingsExtractor (source 16): the /meetings-education/meetings
  listing, which points at ASCO's other satellite/co-sponsored meetings
  (Best of ASCO, IASLC Lung Cancer, Head & Neck Symposium, etc).

Both share helpers (date parsing, image extraction, description trim).
"""

import re
import html as _html
from datetime import date
from typing import Dict, Any, Optional, Callable, List

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS_FULL = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
_MONTHS_ANY = dict(_MONTHS_FULL)
for k, v in list(_MONTHS_FULL.items()):
    _MONTHS_ANY[k[:3]] = v
_MONTHS_ANY["sept"] = 9


def _parse_us_date_range(text: str) -> tuple:
    """Parse 'June 4 - 8, 2027' or 'June 4-8, 2027' → (start_iso, end_iso).
    Handles 'June 4, 2027' single-day too."""
    # "Month Day1 - Day2, Year"
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s+(\d{4})",
        text, re.I,
    )
    if m:
        mon = _MONTHS_FULL[m.group(1).lower()]
        d1, d2, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
        return f"{y:04d}-{mon:02d}-{d1:02d}", f"{y:04d}-{mon:02d}-{d2:02d}"
    # Single day
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        text, re.I,
    )
    if m:
        mon = _MONTHS_FULL[m.group(1).lower()]
        d, y = int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}", f"{y:04d}-{mon:02d}-{d:02d}"
    return None, None


def _strip_and_normalise(raw_html: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw_html)
    txt = _html.unescape(txt)  # unescape BEFORE normalise (BTOG lesson)
    txt = re.sub(r"\s+", " ", txt)
    return txt


def _extract_og_image(html: str) -> Optional[str]:
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
    return m.group(1) if m else None


def _is_real_asco_page(raw_html: str) -> bool:
    """ASCO's CDN returns HTTP 200 with 'Oops! Page Not Found' for
    URLs that don't exist yet (like /annual-meeting/register when
    registration hasn't opened). Detect this so we skip the placeholder.
    """
    return "Oops! Page Not Found" not in raw_html and "Page Not Found" not in raw_html[:2000]


def _fetch_asco_subpage(base_url: str, suffix: str, timeout: float = 25) -> Optional[str]:
    """Fetch an ASCO sub-page. Returns raw HTML if the page is real,
    None if it's a 'Page Not Found' placeholder or fetch failed."""
    url = base_url.rstrip("/") + "/" + suffix.lstrip("/")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(url)
            if r.status_code != 200:
                return None
            if not _is_real_asco_page(r.text):
                return None
            return r.text
    except Exception as e:
        logger.warning(f"ASCO sub-page fetch failed for {url}: {e}")
        return None


def _extract_asco_pricing(sub_html: str) -> List[dict]:
    """ASCO uses USD tiers. Common formats:

    Format 1 - Member/Non-member across 3 timeframes (Quality Care 2026):
      Physician/Scientist    $945/$1,450  $1,095/$1,600  $1,170/$1,675
      In-Training*           $275/$360    $425/$510      $500/$585

    Format 2 - Single-price rows (simpler events):
      Member — $850    Non-member — $1,200

    Format 3 - Column table:
      Registration Type       Early    Standard   Late
      Member                  $850     $1050      $1250
    """
    tiers: List[dict] = []
    seen: set = set()
    txt = re.sub(r"<[^>]+>", " ", sub_html)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)

    # Column labels — try to detect Early/Regular/Late from context
    # (ASCO uses "Advance" / "Regular" / "Late" or "Early" / "Regular" / "Late")
    hdr = re.search(
        r"(?i)(Advance|Early)(?:\s+registration|\s+bird)?"
        r".{0,300}?"
        r"(Regular|Standard)(?:\s+registration)?"
        r".{0,300}?"
        r"(Late|Onsite)(?:\s+registration)?",
        txt,
    )
    col_labels = None
    if hdr:
        col_labels = [
            f"{hdr.group(1).title()} registration",
            f"{hdr.group(2).title()} registration",
            f"{hdr.group(3).title()} registration",
        ]

    # Row labels — expanded to include the Quality Care categories
    row_label_re = re.compile(
        r"(ASCO\s+Member(?:\s+in\s+Training)?|"
        r"Non-?member(?:\s+Physician)?|Non\s+Member|"
        r"Physician(?:/Scientist)?(?:\s+Member)?|Scientist|"
        r"In-?Training\*?|Trainee|Student|Resident|"
        r"Affiliated\s+Health\s+Professional\*?|"
        r"Allied\s+Health\s+Professional\*?|"
        r"Patient\s+Advocate\*?|"
        r"Early\s+Career,?\s+Retired,?\s+or\s+Emeritus"
        r"(?:\s+\(Member\s+Only\))?|"
        r"Low\s+or\s+Middle\s+Income\s+Country(?:\s+Member\s+Only)?|"
        r"Industry|Press|Media|"
        r"Standard\s+registration|Early\s+registration|Late\s+registration)",
        re.I,
    )

    # Match member/non-member pairs like "$945/$1,450" or singles like "$945"
    # in a row window (up to 400 chars after the label). Order matters:
    # try the pair pattern first so "$945/$1,450" isn't split into two singles.
    pair_re = re.compile(
        r"\$\s*([\d,]+(?:\.\d{2})?)\s*/\s*\$\s*([\d,]+(?:\.\d{2})?)"
    )
    single_re = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")

    def _add(label: str, price: float, currency: str = "USD"):
        label = label.strip()[:200]
        if not label or not (50 <= price <= 20000):
            return
        key = (label.lower(), price)
        if key in seen:
            return
        seen.add(key)
        tiers.append({
            "tier_label": label, "price_gbp": price, "currency": currency,
            "is_early_bird": "early" in label.lower() or "advance" in label.lower(),
            "early_bird_deadline": None,
        })

    for lm in row_label_re.finditer(txt):
        label = re.sub(r"\s+", " ", lm.group(1)).strip()
        window = txt[lm.end(): lm.end() + 400]
        # Try pair format first — indicates member/non-member split.
        # BUT skip pair-splitting if the label already denotes member/nonmember
        # (would produce nonsense like "Nonmember (Member)").
        label_low = label.lower()
        label_already_membership = (
            "member" in label_low or "nonmember" in label_low
            or "non-member" in label_low
        )
        pairs = list(pair_re.finditer(window))
        if pairs and len(pairs) >= 1 and not label_already_membership:
            for idx, pm in enumerate(pairs[:3]):
                col = col_labels[idx] if col_labels and idx < len(col_labels) else None
                try:
                    p_member = float(pm.group(1).replace(",", ""))
                    p_nonmember = float(pm.group(2).replace(",", ""))
                except ValueError:
                    continue
                m_label = f"{label} (Member)" + (f" — {col}" if col else "")
                nm_label = f"{label} (Non-member)" + (f" — {col}" if col else "")
                _add(m_label, p_member)
                _add(nm_label, p_nonmember)
            continue

        # Otherwise fall back to single-price rows
        raw_prices = single_re.findall(window)
        if not raw_prices:
            continue
        max_prices = len(col_labels) if col_labels else 4
        for idx, p in enumerate(raw_prices[:max_prices]):
            try:
                price = float(p.replace(",", ""))
            except ValueError:
                continue
            col = col_labels[idx] if col_labels and idx < len(col_labels) else None
            _add(f"{label}" + (f" — {col}" if col else ""), price)
    return tiers


def _extract_asco_abstract_deadline(sub_html: str) -> Optional[str]:
    """ASCO uses dates like 'February 6, 2027' or 'Feb 6, 2027'."""
    txt = re.sub(r"<[^>]+>", " ", sub_html)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)
    m = re.search(
        r"(?i)(?:abstract\s+submission\s+(?:deadline|closes?|due)|"
        r"submission\s+deadline|deadline\s+for\s+abstracts?)"
        r"[^A-Za-z0-9]{1,40}"
        r"("
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{1,2},?\s+\d{4})",
        txt,
    )
    if not m:
        return None
    return _parse_us_date_single(m.group(1))


def _parse_us_date_single(s: str) -> Optional[str]:
    """Parse 'February 6, 2027' → '2027-02-06'.

    Also handles fuzzy prefixes like 'EARLY/MID/LATE MONTH YEAR' by
    substituting approximate day numbers (Early=5, Mid=15, Late=25).
    This lets us reason about "LATE APRIL 2026" being in the past vs
    the future rather than treating it as unparseable.
    """
    if not s:
        return None
    ss = s.strip()
    # Try exact Month Day, Year first
    dm = re.match(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", ss)
    if dm:
        mon_name = dm.group(1).lower()
        mon = _MONTHS_ANY.get(mon_name) or _MONTHS_ANY.get(mon_name[:3])
        if mon:
            d, y = int(dm.group(2)), int(dm.group(3))
            return f"{y:04d}-{mon:02d}-{d:02d}"
    # Try fuzzy: "EARLY/MID/LATE Month Year"
    fm = re.match(r"(?i)(early|mid|late)\s+([A-Za-z]+),?\s+(\d{4})", ss)
    if fm:
        prefix = fm.group(1).lower()
        mon_name = fm.group(2).lower()
        mon = _MONTHS_ANY.get(mon_name) or _MONTHS_ANY.get(mon_name[:3])
        if mon:
            day_by_prefix = {"early": 5, "mid": 15, "late": 25}
            d = day_by_prefix[prefix]
            y = int(fm.group(3))
            return f"{y:04d}-{mon:02d}-{d:02d}"
    # Try month + year only (no prefix, no day) → assume mid-month
    my = re.match(r"(?i)^([A-Za-z]+)\s+(\d{4})$", ss)
    if my:
        mon_name = my.group(1).lower()
        mon = _MONTHS_ANY.get(mon_name) or _MONTHS_ANY.get(mon_name[:3])
        if mon:
            y = int(my.group(2))
            return f"{y:04d}-{mon:02d}-15"
    return None


def _extract_asco_abstract_opens(sub_html_or_main: str) -> Optional[str]:
    """Look for 'Abstract submission opens' patterns.
    Returns the raw date string (for display in a note) if found.
    """
    txt = re.sub(r"<[^>]+>", " ", sub_html_or_main)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)
    m = re.search(
        r"(?i)abstract\s+submission\s+(?:opens?|begin|starts?|will\s+open|"
        r"is\s+open|available)\s*(?:on|from)?\s*"
        r"("
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{1,2},?\s+\d{4})",
        txt,
    )
    if m:
        return m.group(1)
    # Also match "will open in <Month YYYY>"
    m = re.search(
        r"(?i)abstract\s+submission[^.]{0,60}?(?:will\s+open|opens?)\s+"
        r"(?:in\s+)?"
        r"("
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4})",
        txt,
    )
    if m:
        return m.group(1)
    return None


def _parse_asco_dates_to_know(raw_html: str) -> dict:
    """ASCO's /dates-know sub-page has a structured list of key dates.

    HTML pattern:
      <p><strong>DATE STRING</strong><br>LABEL DESCRIPTION</p>

    Returns dict with:
      abstract_opens: raw date string (e.g. "November 4, 2026")
      abstract_deadline: ISO date if parseable (e.g. "2027-01-26")
      abstract_deadline_raw: raw date string of the deadline
      late_breaking_deadline: LBA deadline (ISO if parseable)
      registration_opens: registration opening date
      hotel_registration_deadline: hotel/early registration deadline
      all_dates: list of (raw_date, label) tuples for audit trail
    """
    out: dict = {"all_dates": []}
    # ASCO wraps each date row in a <p>. Common shapes:
    #   <p><strong>DATE</strong><br>LABEL</p>
    #   <p><strong>DATE AT</strong> <strong>TIME (TZ)</strong><br>LABEL</p>
    #   <p><strong>DATE<br></strong>LABEL</p>
    #   <p><strong>DATE</strong><br>LABEL <strong>PRODUCT</strong></p>
    # A single regex can't cover all cleanly, so grab each <p>...</p>, split
    # on <br>, and strip tags on each half.
    def _clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", " ", s)
        s = _html.unescape(s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    for pm in re.finditer(r"<p\b[^>]*>(.*?)</p>", raw_html, re.I | re.DOTALL):
        inner = pm.group(1)
        if "<br" not in inner.lower():
            continue
        parts = re.split(r"<br\s*/?>", inner, maxsplit=1, flags=re.I)
        if len(parts) != 2:
            continue
        date_raw = _clean(parts[0])
        label = _clean(parts[1])
        if not date_raw or not label:
            continue
        # Skip prose paragraphs — date side must contain a month name or year
        if not re.search(r"(?i)\b(?:january|february|march|april|may|june|"
                         r"july|august|september|october|november|december|"
                         r"early|mid|late|20\d{2})\b", date_raw):
            continue
        out["all_dates"].append((date_raw, label))
        ll = label.lower()

        # Match label -> field
        if re.search(r"abstract\s+submission\s+(?:opens?|launches?|"
                     r"begin|starts?|site\s+open)", ll):
            out.setdefault("abstract_opens", date_raw)
        elif "abstract submission deadline" in ll:
            out["abstract_deadline_raw"] = date_raw
            iso = _parse_us_date_single(re.sub(r",?\s*at\s+.*$", "", date_raw))
            if iso:
                out["abstract_deadline"] = iso
        elif re.search(r"late[\-\s]?breaking\s+(?:abstract\s+)?"
                       r"(?:submission\s+)?(?:deadline|due)", ll):
            iso = _parse_us_date_single(re.sub(r",?\s*at\s+.*$", "", date_raw))
            if iso:
                out["late_breaking_deadline"] = iso
        elif re.search(r"registration\s+(?:and\s+"
                       r"(?:hotel\s+reservations?|housing|hotel)\s+)?"
                       r"(?:opens?|available)", ll):
            out.setdefault("registration_opens", date_raw)
        elif re.search(r"(?:hotel\s+reservation\s+and\s+)?early\s+registration"
                       r"\s+deadline", ll):
            out.setdefault("hotel_registration_deadline", date_raw)
    return out


class ASCOMeetingsExtractor(BaseExtractor):
    """Source 16: ASCO Meetings-Education listing.

    ASCO hosts 4 self-published event pages (short paths on asco.org):
      - /breakthrough  -> ASCO Breakthrough (Asia annual meeting)
      - /gi            -> ASCO Gastrointestinal Cancers Symposium
      - /gu            -> ASCO Genitourinary Cancers Symposium
      - /quality       -> ASCO Quality Care Symposium

    (Also on the listing but excluded: ongoing licensed programs like
    /meetings-education/meetings/asco-direct and /best-of-asco, and
    externally co-sponsored partner meetings like IASLC | ASCO Lung
    Cancer, SNO/ASCO CNS Metastases, AACR/ASCO Methods Workshop and
    Multidisciplinary Head & Neck Symposium.)
    """

    _EVENT_URLS = [
        {
            "title": "ASCO Breakthrough",
            "url": "https://www.asco.org/breakthrough",
            "desc_tokens": ("breakthrough", "asia"),
            "candidate_cities": ("Singapore", "Bangkok", "Kuala Lumpur",
                                  "Hong Kong", "Tokyo", "Yokohama",
                                  "Seoul", "Taipei"),
        },
        {
            "title": "ASCO Gastrointestinal Cancers Symposium",
            "url": "https://www.asco.org/gi",
            "desc_tokens": ("gastrointestinal", "gi cancers"),
            "candidate_cities": ("San Francisco",),
        },
        {
            "title": "ASCO Genitourinary Cancers Symposium",
            "url": "https://www.asco.org/gu",
            "desc_tokens": ("genitourinary", "gu cancers"),
            "candidate_cities": ("San Francisco",),
        },
        {
            "title": "ASCO Quality Care Symposium",
            "url": "https://www.asco.org/quality",
            "desc_tokens": ("quality care", "quality, safety"),
            "candidate_cities": ("Boston",),
        },
    ]

    # Discovery — scan the /meetings-education/meetings page for any
    # short-path URLs like /gi, /gu, /breakthrough, /quality that link
    # to standalone event subsites. This catches new symposia when ASCO
    # adds them (they've historically added ~1 new event per year).
    _LISTING_URL = "https://www.asco.org/meetings-education/meetings"

    # Short paths on asco.org that ARE real event pages, but excluded
    # because they're not single-event pages
    _EXCLUDED_SHORT_PATHS = {
        "search", "contact-us", "abstracts", "posters", "slides", "videos",
        "guidelines", "journals", "annual-meeting",  # separate source
        "asco-licensing-opportunities", "meetings-education",
    }

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Start with the hardcoded curated list — these are known-good
        # entries with proper metadata (candidate_cities, desc_tokens).
        # Then auto-discover any additional short-path event URLs on the
        # listing page — if ASCO adds "ASCO Breast Cancer Symposium" at
        # /breast, we'll pick it up on the next scrape.
        curated_by_url = {e["url"]: e for e in self._EVENT_URLS}
        discovered_urls: set = set()
        try:
            with httpx.Client(timeout=25, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(self._LISTING_URL)
                raw = r.text
            # Find /<short-path> hrefs where short-path is 2-30 chars,
            # single segment, no /meetings-education/ prefix
            for m in re.finditer(
                r'href=["\'](/[a-z][a-z0-9\-]{1,29}|'
                r'https://www\.asco\.org/[a-z][a-z0-9\-]{1,29})["\']',
                raw,
            ):
                url = m.group(1)
                if url.startswith("/"):
                    url = "https://www.asco.org" + url
                url = url.rstrip("/")
                slug = url.rsplit("/", 1)[-1]
                if slug in self._EXCLUDED_SHORT_PATHS:
                    continue
                discovered_urls.add(url)
        except Exception as e:
            logger.warning(f"ASCO listing discovery failed: {e}")

        # Warn if we found any URLs that AREN'T in our curated list —
        # they may be new events we need to add metadata for.
        for url in sorted(discovered_urls):
            if url not in curated_by_url:
                logger.warning(
                    f"ASCO: discovered short-path URL not in curated list: "
                    f"{url} — verify if this is a new event and add to "
                    f"_EVENT_URLS if so"
                )

        return [{
            "title": e["title"],
            "booking_url": e["url"],
            "source_url": e["url"],
            "_meta": e,
        } for e in self._EVENT_URLS]

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or shell.get("booking_url") or ""
        meta = shell.get("_meta") or {}
        title_hint = meta.get("title") or shell.get("title") or ""
        desc_tokens = meta.get("desc_tokens") or (title_hint.lower(),)
        candidate_cities = meta.get("candidate_cities") or ()

        out: Dict[str, Any] = {}
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception as e:
            logger.warning(f"ASCO meetings sub-fetch failed: {e}")
            return out

        txt = _strip_and_normalise(raw)

        # Dates + year prefix
        start, end = _parse_us_date_range(txt)
        if start:
            out["start_date"] = start
            if end and end != start:
                out["end_date"] = end
            year = start[:4]
            out["conference_name"] = f"{year} {title_hint}"
        else:
            out["conference_name"] = title_hint

        # Location — try known candidate cities for this event first
        for city in candidate_cities:
            if city in txt:
                out["city"] = city
                break

        # Venue detection — ASCO uses "location_on Venue Name | City"
        # or "at Moscone West" or "Hynes Convention Center, Boston"
        venue_m = re.search(
            r"location_on\s+([A-Z][A-Za-z0-9 .,'&-]{4,80}?)\s*\|",
            txt,
        )
        if venue_m:
            out["venue_name"] = venue_m.group(1).strip()
        else:
            # Fallback — "Hynes Convention Center, Boston, MA & Online"
            for city in candidate_cities:
                venue_m = re.search(
                    rf"([A-Z][A-Za-z0-9 .,'&-]{{4,80}}?),\s+{re.escape(city)}\b",
                    txt,
                )
                if venue_m:
                    out["venue_name"] = venue_m.group(1).strip()
                    break

        # Format detection
        low = txt.lower()
        if re.search(r"(?:&|and)\s+online", low) or "hybrid" in low:
            out["event_format"] = "hybrid"
        elif "virtual" in low or "online only" in low:
            out["event_format"] = "online"
        else:
            out["event_format"] = "in_person"

        out["event_type"] = "conference"
        out["is_flagship"] = True
        out["specialty"] = "Oncology"
        out["society"] = "ASCO"

        # Description — must mention title-specific tokens
        candidates: List[str] = []
        for tag in ("h1", "h2", "p"):
            for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", raw, re.I | re.S):
                d = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
                d = re.sub(r"\s+", " ", d).strip()
                if not (50 <= len(d) <= 700):
                    continue
                dl = d.lower()
                if not any(t in dl for t in desc_tokens):
                    continue
                if any(bad in dl for bad in ("cookie", "javascript")):
                    continue
                if dl.startswith(("couldn", "did", "want", "why", "how", "what")):
                    continue
                candidates.append(d)
        if candidates:
            candidates.sort(key=len, reverse=True)
            out["description"] = candidates[0]

        # Dates-to-Know sub-page — ASCO's authoritative structured
        # key-dates page. Contains abstract opening/closing dates AND
        # registration deadlines in a consistent <p><strong>date</strong>
        # <br>label</p> pattern.
        dates_html = _fetch_asco_subpage(url, "dates-know")
        opens_raw: Optional[str] = None
        deadline: Optional[str] = None
        if dates_html:
            dtk = _parse_asco_dates_to_know(dates_html)
            opens_raw = dtk.get("abstract_opens")
            deadline = dtk.get("abstract_deadline")

        # Fallback: main page + generic sub-pages
        if not opens_raw:
            opens_raw = _extract_asco_abstract_opens(txt)
        if not deadline:
            for suffix in ("abstracts", "program/abstracts",
                            "attend/abstract-submissions",
                            "abstracts-and-presentations"):
                abs_html = _fetch_asco_subpage(url, suffix)
                if abs_html:
                    if not deadline:
                        deadline = _extract_asco_abstract_deadline(abs_html)
                    if not opens_raw:
                        opens_raw = _extract_asco_abstract_opens(abs_html)
                    if deadline and opens_raw:
                        break

        # Stale-data guard. ASCO occasionally rolls a subsite URL forward
        # to next year's event but leaves the previous cycle's deadline
        # on the page (seen on /breakthrough). Drop the deadline if it's
        # implausibly early (>240 days before start_date); the next daily
        # scrape re-picks the real one once ASCO updates the page.
        if deadline and out.get("start_date"):
            try:
                _d = date.fromisoformat(deadline)
                _s = date.fromisoformat(out["start_date"])
                if (_s - _d).days > 240:
                    logger.info(
                        f"ASCO {shell.get('title', 'event')}: dropping stale "
                        f"abstract deadline {deadline} ({(_s - _d).days} days "
                        f"before event {out['start_date']})"
                    )
                    deadline = None
                    opens_raw = None
            except ValueError:
                pass

        today = date.today().isoformat()
        if deadline:
            out["abstract_deadline"] = deadline
            if opens_raw:
                opens_iso = _parse_us_date_single(opens_raw) or ""
                if opens_iso and opens_iso > today:
                    # Opening date is future → not open yet
                    out["abstract_open"] = False
                    out["abstract_deadline_note"] = f"Opens {opens_raw}"
                else:
                    # Opening date is past (or unknown) → open until deadline
                    out["abstract_open"] = deadline >= today
            else:
                out["abstract_open"] = deadline >= today
        elif opens_raw:
            # No explicit deadline. We know when submissions opened but not
            # when they close, so we can't confirm they're still open. Default
            # to closed and surface the opening date so users see the timeline.
            out["abstract_open"] = False
            out["abstract_deadline_note"] = (
                f"Abstract submission opens {opens_raw}"
            )

        # Registration sub-page for USD pricing tiers. Try nested paths
        # first (used by Quality Care and future symposia).
        for suffix in ("registration-hotels/registration-details",
                        "registration-hotels/registration-and-hotels",
                        "attend/registration-details",
                        "attend/register", "attend/registration",
                        "registration", "register"):
            reg_html = _fetch_asco_subpage(url, suffix)
            if reg_html:
                tiers = _extract_asco_pricing(reg_html)
                if tiers:
                    out["pricing_tiers"] = tiers
                    break

        return out


class ASCOAnnualExtractor(BaseExtractor):
    """Source 15: ASCO Annual Meeting flagship subsite.

    The /annual-meeting page shows one row: whichever ASCO Annual Meeting
    is upcoming (currently 2027). No listing walk — the URL itself IS the
    event's page.
    """

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Return exactly one shell — the event page itself
        return [{
            "title": "ASCO Annual Meeting",
            "booking_url": "https://www.asco.org/annual-meeting",
            "source_url": "https://www.asco.org/annual-meeting",
        }]

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or shell.get("booking_url") or ""
        out: Dict[str, Any] = {}
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception as e:
            logger.warning(f"ASCO Annual fetch failed: {e}")
            return out

        txt = _strip_and_normalise(raw)

        # Dates + implied year in the conference name
        start, end = _parse_us_date_range(txt)
        if start:
            out["start_date"] = start
            if end and end != start:
                out["end_date"] = end
            year_from_date = start[:4]
            out["conference_name"] = f"{year_from_date} ASCO Annual Meeting"
        else:
            out["conference_name"] = "ASCO Annual Meeting"

        # Location detection — anchor to "McCormick Place, Chicago, IL"-shape
        # or "location_on" material icon marker used on the page.
        # First check for known ASCO venues + city combos
        venue_city_m = re.search(
            r"(?:location_on|Location[:\s]+)\s*"
            r"([A-Z][A-Za-z .'&-]{4,80}?),\s+"
            r"(Chicago|Boston|Atlanta|San Francisco|New York|Orlando|Washington|Los Angeles)"
            r",?\s*[A-Z]{0,2}",
            txt,
        )
        if venue_city_m:
            out["venue_name"] = venue_city_m.group(1).strip()
            out["city"] = venue_city_m.group(2).strip()
        else:
            # Try "Chicago" bare mention
            for c in ("Chicago", "Boston", "San Francisco", "Orlando"):
                if c in txt:
                    out["city"] = c
                    break

        # Format — hybrid if "& Online" or "and Online"
        low = txt.lower()
        if re.search(r"(?:&|and)\s+online", low) or "hybrid" in low:
            out["event_format"] = "hybrid"
        elif "virtual" in low or "online only" in low:
            out["event_format"] = "online"
        else:
            out["event_format"] = "in_person"

        out["event_type"] = "conference"
        out["is_flagship"] = True
        out["specialty"] = "Oncology"
        out["society"] = "ASCO"

        # Description — must be about THIS event (the Annual Meeting), not
        # about a different ASCO satellite event that happens to name-check
        # the Annual Meeting. Filters:
        #   1. mentions "annual meeting"
        #   2. does NOT mention other ASCO satellite events by name
        #   3. not an interrogative or clearly navigational
        target_tokens = ("annual meeting", "asco annual")
        # Other ASCO events that might appear in ambient descriptions.
        # If a candidate mentions any of these, it's about a different event.
        other_events = (
            "breakthrough", "quality care", "gastrointestinal",
            "genitourinary", "supportive care", "direct highlights",
            "best of asco", "aacr/asco", "sno/asco", "iaslc",
            "head & neck symposium", "cns metastases",
        )
        candidates: List[str] = []
        for tag in ("h1", "h2", "p"):
            for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", raw, re.I | re.S):
                d = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
                d = re.sub(r"\s+", " ", d).strip()
                if not (50 <= len(d) <= 700):
                    continue
                dl = d.lower()
                if not any(t in dl for t in target_tokens):
                    continue
                if any(bad in dl for bad in ("cookie", "javascript")):
                    continue
                # Reject if mentions other ASCO satellite events
                if any(oe in dl for oe in other_events):
                    continue
                # Reject interrogative openings (they're often nav prompts)
                if dl.startswith(("couldn", "did", "want", "why", "how", "what")):
                    continue
                candidates.append(d)
        if candidates:
            # Prefer the longest surviving candidate
            candidates.sort(key=len, reverse=True)
            out["description"] = candidates[0]

        # Fetch known sub-pages when they exist (ASCO returns 200 with
        # "Oops! Page Not Found" for URLs that don't exist yet).
        # These auto-populate as ASCO publishes info closer to the meeting.
        #
        # Registration sub-page — for USD pricing tiers
        for suffix in ("attend/register", "attend/registration",
                        "registration", "register"):
            reg_html = _fetch_asco_subpage(url, suffix)
            if reg_html:
                tiers = _extract_asco_pricing(reg_html)
                if tiers:
                    out["pricing_tiers"] = tiers
                    break

        # Dates-to-Know sub-page — ASCO's structured key-dates page has
        # the authoritative abstract opening/closing + registration dates
        dates_html = _fetch_asco_subpage(url, "dates-know")
        opens_raw: Optional[str] = None
        deadline: Optional[str] = None
        if dates_html:
            dtk = _parse_asco_dates_to_know(dates_html)
            opens_raw = dtk.get("abstract_opens")
            deadline = dtk.get("abstract_deadline")

        # Fallback: main page + generic sub-pages
        if not opens_raw:
            opens_raw = _extract_asco_abstract_opens(txt)
        if not deadline:
            for suffix in ("abstracts", "program/abstracts",
                            "attend/abstract-submissions",
                            "abstracts-and-presentations"):
                abs_html = _fetch_asco_subpage(url, suffix)
                if abs_html:
                    if not deadline:
                        deadline = _extract_asco_abstract_deadline(abs_html)
                    if not opens_raw:
                        opens_raw = _extract_asco_abstract_opens(abs_html)
                    if deadline and opens_raw:
                        break

        # Stale-data guard. ASCO occasionally rolls a subsite URL forward
        # to next year's event but leaves the previous cycle's deadline
        # on the page (seen on /breakthrough). Drop the deadline if it's
        # implausibly early (>240 days before start_date); the next daily
        # scrape re-picks the real one once ASCO updates the page.
        if deadline and out.get("start_date"):
            try:
                _d = date.fromisoformat(deadline)
                _s = date.fromisoformat(out["start_date"])
                if (_s - _d).days > 240:
                    logger.info(
                        f"ASCO {shell.get('title', 'event')}: dropping stale "
                        f"abstract deadline {deadline} ({(_s - _d).days} days "
                        f"before event {out['start_date']})"
                    )
                    deadline = None
                    opens_raw = None
            except ValueError:
                pass

        today = date.today().isoformat()
        if deadline:
            out["abstract_deadline"] = deadline
            if opens_raw:
                opens_iso = _parse_us_date_single(opens_raw) or ""
                if opens_iso and opens_iso > today:
                    # Opening date is future → not open yet
                    out["abstract_open"] = False
                    out["abstract_deadline_note"] = f"Opens {opens_raw}"
                else:
                    # Opening date is past, deadline known → open until deadline
                    out["abstract_open"] = deadline >= today
            else:
                out["abstract_open"] = deadline >= today
        elif opens_raw:
            # No explicit deadline. Only mark open when both opens is past
            # AND we know the deadline is still future — which we don't here.
            # So default to closed and surface the opening date in the note
            # (users can decide whether to check the source page for status).
            out["abstract_open"] = False
            out["abstract_deadline_note"] = (
                f"Abstract submission opens {opens_raw}"
            )

        # Venue sub-page — for detailed venue info if main page didn't
        # have "McCormick Place, Chicago" pattern
        if "venue_name" not in out:
            for suffix in ("venue", "attend/venue", "attend/hotels", "hotels"):
                v_html = _fetch_asco_subpage(url, suffix)
                if v_html:
                    v_txt = _strip_and_normalise(v_html)
                    # "held at the McCormick Place" or "McCormick Place, Chicago"
                    vm = re.search(
                        r"(?:held\s+at|will\s+take\s+place\s+at|hosted\s+at)"
                        r"\s+(?:the\s+)?"
                        r"([A-Z][A-Za-z0-9 .,'&-]{5,120})",
                        v_txt, re.I,
                    )
                    if vm:
                        v = vm.group(1)
                        for stop in (" in ", " from ", ",", " and ",
                                      " Chicago", " where "):
                            idx = v.find(stop)
                            if idx > 4:
                                v = v[:idx]
                                break
                        v = v.strip().rstrip(",.-;:")
                        if 4 < len(v) < 120:
                            out["venue_name"] = v
                            break
        return out
