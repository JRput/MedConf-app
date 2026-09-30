# extractors/arvo.py
"""
ARVO (Association for Research in Vision and Ophthalmology) — Annual
Meeting extractor.

Wave 1d source. Recon said arvo.org was Cloudflare-"parked"; on
2026-09-28/29 the production browser (browser.py's navigate(), which
rotates to a fresh alternate-profile context the moment it sees a
"Just a moment…" title) clears every page on this domain in well under
a second. This module therefore uses `self.browser.navigate(url)` for
every page load and NEVER holds a `Page` handle across a navigate() call
— a rotation closes the previous page outright (see browser.py
`_switch_to_alt_profile`). Each `_fetch()` below grabs `.content()`
immediately after navigating and only returns the HTML string.

Site shape — this is a DEDICATED FLAGSHIP MICROSITE, not a listing of
many events (PLAYBOOK.md "multi-page detail" pattern, but for the
*whole site*, not one event). `https://www.arvo.org/annual-meeting/` is
marketing home page; the actual data lives on sibling pages that don't
change their URL from year to year — ARVO re-points the same paths at
next year's meeting once the current one wraps:

  /annual-meeting/about/future-meetings  — <table> Year | Date | Location
                                            | Visitor Information, sorted
                                            ascending. This is the most
                                            structured page on the site,
                                            so it drives WHICH year we
                                            report (soonest row whose
                                            date range hasn't passed).
  /annual-meeting/about                  — <details>-style accordions
                                            (content is server-rendered,
                                            just CSS `display:none` — read
                                            raw HTML, not innerText) with
                                            "Important dates" (abstract
                                            open/deadline, early
                                            registration) and "Meeting
                                            location" (full venue address).
  /annual-meeting/registration           — two plain <table>s, no CSS
                                            classes at all: "Rates" (the
                                            core registration fee grid)
                                            and "CME Rates" (the optional
                                            CME-credit processing fee).
                                            Both have the SAME shape:
                                            header row = ["<Section
                                            label>", "<timeframe 1>", ...
                                            "Late"], each data row =
                                            [category, price@tf1, price@
                                            tf2, ...]. pricing_tables.py's
                                            shared parser only keeps ONE
                                            price per row (last non-empty
                                            cell) so it would silently
                                            drop the Early Bird / Standard
                                            tiers — not usable here, hence
                                            the bespoke `_rate_tables()`.
                                            Also states plainly "scheduled
                                            to be in-person only and will
                                            not have a virtual component"
                                            — deterministic event_format.
  /annual-meeting/abstracts              — plain-text submission window
                                            ("Submission will open from
                                            Oct. 16 to Dec. 4, 2026"), used
                                            only as a fallback for the
                                            deadline if the /about
                                            accordion parse comes up empty.

All fees are in USD (this is an international body; the recon guess was
right). `price_gbp` on every tier actually holds the USD amount, with
`currency: "USD"` set — the same convention `RCOGExtractor` uses for its
World Congress tiers.

CPD: the Meeting is an accredited CME activity (AMA PRA Category 1
Credit™), but ARVO never states a numeric hour/credit count anywhere on
the public pages — cpd_points stays None, cpd_accredited=True.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from .base import BaseExtractor
from .abstract_classifier import extract_abstract_info
from .specialty_classifier import classify_specialty
from logger import logger

BASE_URL = "https://www.arvo.org/annual-meeting"
_CHALLENGE_TITLE_RE = re.compile(r"<title>\s*(?:just a moment|attention required)", re.I)
FUTURE_MEETINGS_URL = f"{BASE_URL}/about/future-meetings"
ABOUT_URL = f"{BASE_URL}/about"
REGISTRATION_URL = f"{BASE_URL}/registration"
ABSTRACTS_URL = f"{BASE_URL}/abstracts"
CME_URL = f"{BASE_URL}/about/cme"

_MONTHS = {
    m.lower()[:3]: i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}
_MONTH_RE = "|".join(_MONTHS)

# US state / territory abbreviations ARVO writes on the Future Meetings
# table ("San Diego, Calif.", "Seattle, Wash."). Extend as new host
# cities show up; anything not in here is passed through unmapped
# (e.g. "Canada", "Hawaiʻi" already reads fine as-is).
_US_STATE_ABBR = {
    "calif.": "California",
    "wash.": "Washington",
    "mass.": "Massachusetts",
    "fla.": "Florida",
    "ga.": "Georgia",
    "ill.": "Illinois",
    "tex.": "Texas",
    "ariz.": "Arizona",
    "colo.": "Colorado",
    "nev.": "Nevada",
    "ore.": "Oregon",
    "pa.": "Pennsylvania",
    "md.": "Maryland",
    "mich.": "Michigan",
    "minn.": "Minnesota",
    "mo.": "Missouri",
    "tenn.": "Tennessee",
    "wis.": "Wisconsin",
}


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    return html_lib.unescape(text).replace("\xa0", " ").replace("ʻ", "'")


def _flatten(fragment: str) -> str:
    return re.sub(r"\s+", " ", _strip_tags(fragment)).strip()


class ARVOExtractor(BaseExtractor):
    """Browser-first extractor for arvo.org's Annual Meeting microsite."""

    # ------------------------------------------------------------------ #
    # Fetch helper — navigate, then read content IMMEDIATELY. Never keep
    # a Page reference across a subsequent navigate() (wave 1d addendum:
    # a Cloudflare-context rotation closes the previous page).
    # ------------------------------------------------------------------ #
    def _fetch(self, url: str) -> Optional[str]:
        browser = getattr(self, "browser", None)
        if browser is None:
            logger.warning("ARVO: no browser available")
            return None
        # arvo.org's Cloudflare clears from GitHub-runner IPs only
        # intermittently (2 of 3 probes on 2026-09-30), so retry a couple
        # of times; navigate() rotates to a fresh browser context each go.
        for attempt in range(3):
            try:
                browser.navigate(url)
                html = browser.page.content()
                if not _CHALLENGE_TITLE_RE.search(html[:2000]):
                    return html
                logger.warning(f"ARVO: still challenged on {url} (attempt {attempt + 1}/3)")
            except Exception as e:
                logger.warning(f"ARVO: fetch of {url} failed (attempt {attempt + 1}/3): {e}")
        return None

    # ------------------------------------------------------------------ #
    # Phase A — listing override: ONE shell for whichever meeting the
    # Future Meetings table says is next.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(FUTURE_MEETINGS_URL)
        if not html:
            logger.warning("ARVO: future-meetings page unavailable — no shells")
            return []

        rows = self._parse_future_meetings(html)
        if not rows:
            logger.warning("ARVO: future-meetings table not found/parsed — no shells")
            return []

        today = date.today()
        upcoming = [r for r in rows if (r["end_date"] or r["start_date"]) >= today]
        if not upcoming:
            logger.warning("ARVO: no upcoming rows in future-meetings table")
            return []
        row = min(upcoming, key=lambda r: r["start_date"])

        shell = {
            "title": f"ARVO Annual Meeting {row['year']}",
            "booking_url": REGISTRATION_URL,
            "start_date": row["start_date"].isoformat(),
            "end_date": row["end_date"].isoformat() if row["end_date"] else None,
            "city": row["city"],
            "region": row["region"],
            "category": "conference",
        }
        logger.info(f"ARVO: next meeting is {shell['title']} ({shell['start_date']})")
        return [shell]

    @staticmethod
    def _parse_future_meetings(html: str) -> List[Dict[str, Any]]:
        """Year | Date | Location | Visitor Information -> parsed rows.

        Date column is "May 2 - 6" (single month) or "April 30 - May 4"
        (crosses a month boundary); year always comes from the Year column,
        never guessed.
        """
        m = re.search(r"(?is)<table[^>]*>(.*?)</table>", html)
        if not m:
            return []
        rows_html = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(1))
        out: List[Dict[str, Any]] = []
        for row_html in rows_html:
            cells = [_flatten(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row_html)]
            if len(cells) < 3 or not re.fullmatch(r"\d{4}", cells[0]):
                continue
            year = int(cells[0])
            start, end = ARVOExtractor._parse_date_range(cells[1], year)
            if not start:
                continue
            city, region = ARVOExtractor._parse_location(cells[2])
            out.append({
                "year": year, "start_date": start, "end_date": end,
                "city": city, "region": region,
            })
        return out

    @staticmethod
    def _parse_date_range(text: str, year: int) -> Tuple[Optional[date], Optional[date]]:
        """"May 2 - 6" -> (May 2, May 6); "April 30 - May 4" -> (Apr 30, May 4)."""
        text = re.sub(r"\s*[-–—]\s*", " - ", text.strip())
        m = re.fullmatch(
            rf"(?i)({_MONTH_RE})[a-z]*\s+(\d{{1,2}})\s*-\s*(?:({_MONTH_RE})[a-z]*\s+)?(\d{{1,2}})",
            text,
        )
        if not m:
            return None, None
        mon1, day1, mon2, day2 = m.groups()
        mon1_n = _MONTHS[mon1.lower()[:3]]
        mon2_n = _MONTHS[mon2.lower()[:3]] if mon2 else mon1_n
        try:
            start = date(year, mon1_n, int(day1))
            end = date(year, mon2_n, int(day2))
        except ValueError:
            return None, None
        return start, end

    @staticmethod
    def _parse_location(text: str) -> Tuple[Optional[str], Optional[str]]:
        """"San Diego, Calif." -> ("San Diego", "California"); "Toronto,
        Canada" -> ("Toronto", "Canada")."""
        parts = [p.strip().rstrip(",") for p in text.split(",") if p.strip()]
        if not parts:
            return None, None
        city = parts[0]
        if len(parts) == 1:
            return city, None
        tail = parts[-1]
        region = _US_STATE_ABBR.get(tail.lower(), tail)
        return city, region

    # ------------------------------------------------------------------ #
    # Phase B — detail. `page` is already on REGISTRATION_URL (the shell's
    # booking_url); read it first, then walk the remaining sub-pages.
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        reg_html = self._page_html_if_usable(page) or self._fetch(REGISTRATION_URL) or ""
        about_html = self._fetch(ABOUT_URL) or ""
        abstracts_html = self._fetch(ABSTRACTS_URL) or ""
        cme_html = self._fetch(CME_URL) or ""

        result: Dict[str, Any] = {
            "event_type": "conference",
            "is_flagship": True,
            "organiser_url": BASE_URL + "/",
            "pricing_tiers": self._rate_tables(reg_html),
            "event_format": self._event_format(reg_html),
        }
        result.update(self._location(about_html, shell))
        result.update(self._abstract_info(about_html, abstracts_html))
        result["cpd_accredited"] = bool(
            re.search(r"(?i)accredited continuing education", about_html + cme_html)
        )
        result["cpd_points"] = None

        overview_text = self._overview_text(about_html)
        result.update(self._soft_fields(shell.get("title"), overview_text, shell, llm_call))

        return {k: v for k, v in result.items() if v is not None}

    @staticmethod
    def _page_html_if_usable(page: Optional[Page]) -> Optional[str]:
        """The handed-in page, but only if it really is the registration
        page — not a stale page left over from a failed Cloudflare-rotation
        (browser.py's navigate() falls back to whatever page it had before
        when BOTH profiles get challenged; that page can be a different
        arvo.org sub-page)."""
        if page is None:
            return None
        try:
            if "/registration" not in (getattr(page, "url", "") or ""):
                return None
            html = page.content()
        except Exception:
            return None
        return html if "Registration Rates" in html or "Rates</strong>" in html else None

    # ------------------------------------------------------------------ #
    # Pricing — two plain <table>s: registration rates + CME credit fee.
    # Multi-column (one column per timeframe), so pricing_tables.py's
    # single-price-per-row parser doesn't fit; see module docstring.
    # ------------------------------------------------------------------ #
    def _rate_tables(self, html: str) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for tbl in re.findall(r"(?is)<table[^>]*>(.*?)</table>", html):
            rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tbl)
            if not rows:
                continue
            header_cells = [_flatten(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rows[0])]
            if len(header_cells) < 2:
                continue
            section_label, timeframes = header_cells[0], header_cells[1:]
            section = "CME Credit Fee" if "cme" in section_label.lower() else "Registration"

            for row in rows[1:]:
                cells = [_flatten(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)]
                if len(cells) < 2:
                    continue
                category = cells[0]
                for timeframe, price_cell in zip(timeframes, cells[1:]):
                    price = self._parse_usd(price_cell)
                    if price is None:
                        continue
                    is_early = bool(re.search(r"(?i)early\s*bird", timeframe))
                    tiers.append({
                        "tier_label": f"{section} · {category} · {timeframe}"[:160],
                        "price_gbp": price,
                        "currency": "USD",
                        "is_early_bird": is_early,
                        "early_bird_deadline": self._parse_until_date(timeframe) if is_early else None,
                    })
        # De-dupe (responsive/mobile shadow copies of the same table).
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key not in seen:
                seen.add(key)
                out.append(t)
        return out

    @staticmethod
    def _parse_usd(text: str) -> Optional[float]:
        m = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", text)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _parse_until_date(text: str) -> Optional[str]:
        """"Early Bird until March 10, 2027" -> "2027-03-10"."""
        m = re.search(rf"(?i)({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", text)
        if not m:
            return None
        mon, day, year = m.groups()
        try:
            return date(int(year), _MONTHS[mon.lower()[:3]], int(day)).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _event_format(reg_html: str) -> Optional[str]:
        text = _flatten(reg_html)
        if re.search(r"(?i)in-person only and will not have a virtual component", text):
            return "in_person"
        if re.search(r"(?i)\bhybrid\b", text):
            return "hybrid"
        return "in_person"  # ARVO's Annual Meeting has been in-person-only for recent cycles

    # ------------------------------------------------------------------ #
    # Venue — the "Meeting location" accordion on /about (server-rendered,
    # just display:none — read raw HTML, never innerText).
    # ------------------------------------------------------------------ #
    def _location(self, about_html: str, shell: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "city": shell.get("city"),
            "region": shell.get("region"),
            "venue_name": None,
        }
        m = re.search(
            r"(?is)Meeting location.*?<div[^>]*class=\"accordion-content[^\"]*\"[^>]*>(.*?)</div>\s*</div>",
            about_html,
        )
        if not m:
            return out
        address = _flatten(m.group(1))
        if not address:
            return out
        # "The San Diego Convention Center is located at 111 Harbor Dr.,
        # San Diego, Calif. 92101" -> venue name is everything before
        # "is located at".
        venue_m = re.match(r"(?i)^(?:the\s+)?(.+?)\s+is located at\b", address)
        if venue_m:
            out["venue_name"] = venue_m.group(1).strip()
        return out

    # ------------------------------------------------------------------ #
    # Abstracts — the "Important dates" accordion on /about, with the
    # /abstracts page's plain-text submission window as a fallback.
    # ------------------------------------------------------------------ #
    def _abstract_info(self, about_html: str, abstracts_html: str) -> Dict[str, Any]:
        deadline: Optional[date] = None

        m = re.search(
            r"(?is)Important dates.*?<div[^>]*class=\"accordion-content[^\"]*\"[^>]*>(.*?)</div>\s*</div>",
            about_html,
        )
        if m:
            block = m.group(1)
            year = None
            for item_m in re.finditer(r"(?is)<p>(.*?)</p>", block):
                item = _flatten(item_m.group(1))
                if re.fullmatch(r"\d{4}", item):
                    year = int(item)
                    continue
                if year and re.search(r"(?i)abstract submission deadline", item):
                    date_m = re.match(rf"(?i)({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})", item)
                    if date_m:
                        mon, day = date_m.groups()
                        try:
                            deadline = date(year, _MONTHS[mon.lower()[:3]], int(day))
                        except ValueError:
                            pass

        if deadline is None and abstracts_html:
            text = _flatten(abstracts_html)
            win_m = re.search(
                rf"(?i)submission will open from\s+({_MONTH_RE})[a-z]*\.?\s+\d{{1,2}}\s+to\s+"
                rf"({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}}),\s*(\d{{4}})",
                text,
            )
            if win_m:
                _, mon2, day2, year2 = win_m.groups()
                try:
                    deadline = date(int(year2), _MONTHS[mon2.lower()[:3]], int(day2))
                except ValueError:
                    pass
            else:
                # Last resort: the shared deterministic classifier.
                is_open, parsed = extract_abstract_info(text)
                if parsed:
                    deadline = parsed

        if deadline is None:
            return {}
        today = date.today()
        return {
            "abstract_open": deadline >= today,
            "abstract_deadline": deadline.isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Overview text for the LLM — the "Meeting information" prose on
    # /about, before the accordions (dates/venue are already handled
    # deterministically above; this section is what's left for the LLM
    # to summarise, per PLAYBOOK "never pass raw page text" rule).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _overview_text(about_html: str) -> str:
        m = re.search(
            r"(?is)Meeting information(.*?)(?:Our Global Why|Register early and save|Important dates)",
            about_html,
        )
        if not m:
            return _flatten(about_html)[:1200]
        return _flatten(m.group(1))[:1500]

    def _soft_fields(
        self,
        title: Optional[str],
        body_text: str,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        text = body_text[:3000]

        if text:
            prompt = f"""You are summarising the homepage of a single medical/scientific conference. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/research area (e.g. Ophthalmology, Vision Research, Retinal Disease)" or null
}}"""
            raw = llm_call(prompt)
            if raw:
                raw = raw.strip()
                if raw.startswith("```"):
                    parts = raw.split("```")
                    if len(parts) >= 3:
                        raw = parts[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                        raw = raw.strip()
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        result["description"] = parsed.get("description") or None
                        result["specialty"] = parsed.get("specialty") or None
                    except Exception as e:
                        logger.warning(f"ARVO soft-fields JSON parse failed: {e}")

        if not result.get("specialty"):
            result["specialty"] = classify_specialty(title, text) or "Ophthalmology"
        if not result.get("description"):
            result["description"] = self._first_paragraph(body_text) or shell.get("description_hint")
        return result

    @staticmethod
    def _first_paragraph(body_text: str) -> Optional[str]:
        for line in re.split(r"\n+", body_text):
            line = line.strip()
            if len(line) < 60 or line.startswith("http") or "$" in line:
                continue
            if len(line) <= 400:
                return line
            cut = line[:400].rsplit(". ", 1)
            return (cut[0] + ".") if len(cut) == 2 else line[:400].rstrip() + "…"
        return None
