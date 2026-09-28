"""
International AIDS Society (IAS) — conferences extractor.

Drupal site, Cloudflare-fronted. Per the wave 1d addendum, the production
browser clears the challenge on every load via BrowserController.navigate()'s
context rotation (verified 2026-09-28/29) — this module never touches
fetch_html()/httpx and never holds a Page handle across a navigate() call.

There is no dated events/courses LISTING page on this site (recon's "parked"
verdict was wrong about the domain, right that nothing obvious exists at
/events, /conferences, /meeting etc — those 404). What the site actually has
is a handful of flagship, once-every-1-2-years conferences, each living on
its own marketing subsite at /conferences/<slug>. The homepage's "Conferences"
mega-menu is the closest thing to an index: it names exactly the upcoming
and most-recent-past conferences as a fixed set of <nav aria-labelledby=...>
blocks, one per conference, each with an <h2> title and one "Find out more"
link. That menu is what list_shells_override() parses (2026-09-29 it names
three: HIVR4P 2027, IAS 2027, AIDS 2026 — the last already ran, in Rio, so
its subsite is a retrospective with no date banner and gets filtered out
naturally by the "no date found" rule below rather than a hardcoded name).

Each conference subsite is a single, very thin page:
  - A "D[–-]D Month YYYY" date banner directly above the H1
    ("12–15 July 2027", "10–12 July 2027").
  - One intro paragraph: "<Name> will take place in <City>, <Country>, and
    virtually from <dates>." — this is the only source of city/country and
    of the hybrid/in-person format ("and virtually" => hybrid).
  - No venue name, no pricing, no CPD (IAS conferences aren't UK CPD
    accredited), no abstract-submission text yet — these subsites are built
    out closer to the date. Nothing here should be invented; pricing_tiers
    stays [] and cpd/abstract fields are simply omitted (None) until the
    site actually publishes them.

Because the whole page is ~2.2KB of real text, extract_detail() re-derives
everything from the page text itself rather than trusting a cache from the
listing phase — cheap, and avoids ever assuming a stale Page is still good.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from .base import BaseExtractor
from .abstract_classifier import extract_abstract_info
from .specialty_classifier import classify_specialty
from logger import logger

BASE_URL = "https://www.iasociety.org"

_CHALLENGE_TITLE = re.compile(r"just a moment|attention required", re.I)

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}
_MONTH_RE = "|".join(_MONTHS)

# "28 June – 2 July 2027" (spans two months)
_CROSS_MONTH_RE = re.compile(
    rf"(?i)\b(\d{{1,2}})\s+({_MONTH_RE})\s*[–—-]\s*(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b"
)
# "12–15 July 2027" / "12-15 July 2027" / "12 - 15 July 2027"
_SAME_MONTH_RE = re.compile(
    rf"(?i)\b(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b"
)
# "12 July 2027" (single day)
_SINGLE_DAY_RE = re.compile(rf"(?i)\b(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b")

# "<Name> will take place in <City>[, <Region>], <Country>, and virtually"
_LOCATION_RE = re.compile(
    r"(?i)will take place in ([A-Za-zÀ-ſ' .-]+?),\s*([A-Za-zÀ-ſ' .-]+?)"
    r"(?:,\s*and (?:virtually|online))?[.,]"
)

# Mega-menu block on the homepage: one per conference. Each block is a
# <nav aria-labelledby="menu-..."> with one <h2> title and (somewhere inside,
# sometimes wrapped in a <span>, sometimes a plain link) an href to its
# /conferences/<slug> subsite. A naive "h2 ... href" regex over the whole
# document overruns into the WRONG block (menu-main's own h2 "Main
# navigation" paired with a /conferences/ href several blocks later, since
# lazy .*? has no notion of nav boundaries) — so blocks are sliced between
# consecutive `aria-labelledby="menu-...` markers instead, and each slice is
# searched independently.
_MENU_MARKER_RE = re.compile(r'aria-labelledby="menu-[^"]*"')
_H2_RE = re.compile(r"(?s)<h2[^>]*>(.*?)</h2>")
_CONF_HREF_RE = re.compile(r'href="(/conferences/[^"?#]+)"')


def _flatten(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as html_lib
    return html_lib.unescape(re.sub(r"\s+", " ", text)).strip()


def _parse_date_range(text: str) -> Tuple[Optional[date], Optional[date]]:
    m = _CROSS_MONTH_RE.search(text)
    if m:
        d1, mon1, d2, mon2, year = m.groups()
        try:
            start = date(int(year), _MONTHS[mon1.lower()], int(d1))
            end = date(int(year), _MONTHS[mon2.lower()], int(d2))
            return start, end
        except ValueError:
            pass
    m = _SAME_MONTH_RE.search(text)
    if m:
        d1, d2, mon, year = m.groups()
        try:
            start = date(int(year), _MONTHS[mon.lower()], int(d1))
            end = date(int(year), _MONTHS[mon.lower()], int(d2))
            return start, (end if end != start else None)
        except ValueError:
            pass
    m = _SINGLE_DAY_RE.search(text)
    if m:
        d1, mon, year = m.groups()
        try:
            return date(int(year), _MONTHS[mon.lower()], int(d1)), None
        except ValueError:
            pass
    return None, None


class IASExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Phase A — the homepage's "Conferences" mega-menu stands in for a
    # listing page. No pagination; a handful of entries at most.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        if browser is None:
            logger.warning("IAS: no browser available")
            return None

        browser.navigate(BASE_URL + "/")
        home_html = browser.page.content()
        if _CHALLENGE_TITLE.search(browser.page.title() or ""):
            logger.warning("IAS: homepage still challenged after navigate()")
            return None

        candidates: List[Tuple[str, str]] = []
        seen_urls: set = set()
        # Deliberately a SHORT window, not "to the next marker": the mega-menu
        # nests unrelated dropdowns (e.g. the top-level "Conferences" button's
        # own href sits, unmarked, deep inside the "Our People" block's true
        # span) so a wide slice can pair one block's h2 with a stray href from
        # a sibling block several KB away. In every real conference block the
        # <h2> is right at the marker and its href is <400 chars later.
        WINDOW = 900
        for marker in _MENU_MARKER_RE.finditer(home_html):
            block = home_html[marker.start(): marker.start() + WINDOW]
            h2_m = _H2_RE.search(block)
            href_m = _CONF_HREF_RE.search(block)
            if not h2_m or not href_m:
                continue
            title = _flatten(h2_m.group(1))
            href = href_m.group(1)
            if not title or title.lower() in ("main navigation", "conferences links"):
                continue
            url = BASE_URL + href if href.startswith("/") else href
            if url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append((title, url))

        if not candidates:
            logger.warning("IAS: mega-menu produced no conference links")
            return None

        today = date.today()
        shells: List[Dict[str, Any]] = []
        for title, url in candidates:
            browser.navigate(url)
            if _CHALLENGE_TITLE.search(browser.page.title() or ""):
                logger.warning(f"IAS: {url} still challenged — skipping")
                continue
            text = browser.get_page_text()
            start, end = _parse_date_range(text)
            if start is None:
                # No date banner => either a past conference whose subsite
                # has been rewritten into a retrospective (AIDS 2026), or an
                # edition not yet announced. Either way, not scrapeable.
                logger.info(f"IAS: no date on '{title}' ({url}) — skipping")
                continue
            if (end or start) < today:
                logger.info(f"IAS: '{title}' already passed ({start}) — skipping")
                continue
            shells.append(
                {
                    "title": title,
                    "booking_url": url,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat() if end else None,
                }
            )

        logger.info(f"IAS: {len(shells)} upcoming shells of {len(candidates)} menu entries")
        return shells

    # ------------------------------------------------------------------ #
    # Phase B — detail. Re-derives everything from the page text; the whole
    # subsite is one page (~2KB of real content), so there's nothing to gain
    # from trusting a cached copy from Phase A.
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url")
        text = self._usable_text(page, url)
        if not text:
            logger.warning(f"IAS: no usable detail text for {url}")
            return {}

        result: Dict[str, Any] = {"event_type": "conference"}

        start, end = _parse_date_range(text)
        if start:
            result["start_date"] = start.isoformat()
            result["end_date"] = end.isoformat() if end else None

        result.update(self._location_and_format(text))

        is_open, deadline = extract_abstract_info(text)
        if is_open or deadline:
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None

        result["pricing_tiers"] = []  # never published this far ahead; no fee on page => []
        result.update(self._soft_fields(shell.get("title"), text, llm_call))
        return {k: v for k, v in result.items() if v is not None}

    def _usable_text(self, page: Optional[Page], url: Optional[str]) -> str:
        browser = getattr(self, "browser", None)
        try:
            if page is not None and not _CHALLENGE_TITLE.search(page.title() or ""):
                text = page.inner_text("body")
                if "IAS" in text or "HIV" in text:
                    return text
        except Exception:
            pass
        if browser is None or not url:
            return ""
        browser.navigate(url)
        if _CHALLENGE_TITLE.search(browser.page.title() or ""):
            return ""
        return browser.get_page_text()

    @staticmethod
    def _location_and_format(text: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"venue_name": None, "city": None, "region": None,
                                "event_format": None}
        m = _LOCATION_RE.search(text)
        if m:
            out["city"] = m.group(1).strip(" .")
            out["region"] = m.group(2).strip(" .")
        if re.search(r"(?i)\band virtually\b|\bin person and virtually\b|\bhybrid\b", text):
            out["event_format"] = "hybrid"
        elif out["city"]:
            out["event_format"] = "in_person"
        return out

    @staticmethod
    def _soft_fields(
        title: Optional[str], text: str, llm_call: Callable[[str], Optional[str]]
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        # Trim to the real intro content — drop nav/footer boilerplate that
        # precedes/follows the one or two paragraphs that matter.
        body = text
        m = re.search(r"(?i)Breadcrumb", text)
        if m:
            body = text[m.end():]
        m = re.search(r"(?i)Quick links to our activities", body)
        if m:
            body = body[: m.start()]
        body = body.strip()[:3000]

        if body:
            prompt = f"""You are summarising a single conference page from the International AIDS Society (IAS). Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{body}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/scientific topic area (e.g. HIV Medicine, Infectious Disease, HIV Prevention Research)" or null
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
                m2 = re.search(r"\{.*\}", raw, re.DOTALL)
                if m2:
                    import json
                    try:
                        parsed = json.loads(m2.group(0))
                        result["description"] = parsed.get("description") or None
                        result["specialty"] = parsed.get("specialty") or None
                    except Exception as e:
                        logger.warning(f"IAS soft-fields JSON parse failed: {e}")

        if not result.get("specialty"):
            result["specialty"] = classify_specialty(title, body) or "Infectious Disease"
        if not result.get("description"):
            result["description"] = IASExtractor._first_paragraph(body)
        return result

    @staticmethod
    def _first_paragraph(body: str) -> Optional[str]:
        for line in re.split(r"\n+", body):
            line = line.strip()
            if len(line) < 60:
                continue
            if len(line) <= 320:
                return line
            cut = line[:320].rsplit(". ", 1)
            return (cut[0] + ".") if len(cut) == 2 else line[:320].rstrip() + "…"
        return None
