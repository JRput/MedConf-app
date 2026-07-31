# extractors/rcr.py
"""
Royal College of Radiologists (RCR) extractors.

source 11: RCR Global AI Conference 2026 — single flagship event at
  rcraiconference.com/2026 with multi-page subsite. Fees as images so
  per-tier prices aren't extracted.

source 12: my.rcr.ac.uk events portal — Salesforce Lightning Web Components
  community page rendered in shadow DOM. Each event tile has no exposed
  <a href>, only an internal LWC click handler that navigates to a stable
  URL like /event/<recordId>/<slug>. The portal extractor:
    1. Opens the listing in a real browser, waits 15s + scrolls to populate
       the shadow DOM with all visible tiles.
    2. For each tile, looks up by sha256(normalised_title) against existing
       rows in `conferences`. Match = reuse stored URL, no click needed.
    3. For NEW tiles, clicks programmatically and captures window.location
       after the navigation settles. ~3-5s per click, so the FIRST scrape
       is slow (~150s for 30 events). Steady state is fast (~10-15s).
    4. Detail pages are read via document.body.innerText after a 12s wait
       and parsed with section markers ("Event type is", "Start and end
       date of the event", "Event description").
"""

import hashlib
import json
import re
from typing import Dict, Any, Optional, Callable, List

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger


class RCRAIConferenceExtractor(BaseExtractor):
    """RCR Global AI Conference 2026 — flagship subsite."""

    SOURCE_ID = 11

    BASE = "https://rcraiconference.com/2026"
    SUBPAGES = [
        "",
        "/pages/ai-conference-programme",
        "/pages/fees",
        "/pages/attendees",
        "/pages/plan-your-visit",
        "/pages/Late-Abstracts",  # for abstract deadline + open/closed status
    ]

    # ------------------------------------------------------------------ #
    # Listing override — single-shell flagship pattern
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        return [{
            "title": "RCR Global AI Conference 2026",
            "booking_url": self.BASE,
            "category": "conference",
        }]

    # ------------------------------------------------------------------ #
    # Detail extraction
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Walk the sub-pages to collect description content
        combined_text_parts: List[str] = []
        for sub in self.SUBPAGES:
            url = self.BASE + sub
            try:
                if sub:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                body = page.evaluate(r"""() => {
                    const main = document.querySelector(
                        'main, article, [role="main"], #content, .content, .page-content'
                    ) || document.body;
                    const clone = main.cloneNode(true);
                    clone.querySelectorAll(
                        'nav, footer, script, style, noscript, header, .menu, .nav, .navbar'
                    ).forEach(n => n.remove());
                    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
                }""") or ""
                combined_text_parts.append(body)
            except Exception as e:
                logger.warning(f"RCR AI Conference sub-page {url} failed: {e}")

        combined_text = "\n\n".join(combined_text_parts)

        # Hard-coded facts from the homepage — these are stable across the
        # conference cycle and the fees page publishes prices only as images,
        # so we encode the meta here and link out for pricing.
        result: Dict[str, Any] = {
            "conference_name": "RCR Global AI Conference 2026",
            "start_date": "2026-06-29",
            "end_date": "2026-06-30",
            "venue_name": "QEII Centre, Westminster",
            "city": "London",
            "region": "London",
            "event_format": "hybrid",
            "event_type": "conference",
            "is_flagship": True,
            "specialty": "Radiology",
            "cpd_accredited": True,
            "cpd_points": self._first_cpd_from(combined_text),
            "booking_url": f"{self.BASE}/pages/fees",
            "organiser_url": self.BASE,
            # RCR publishes the fee tables as PNG images on /pages/fees.
            # We extract them via the NVIDIA-hosted Llama 3.2 Vision model
            # (see medconf-scraper/vision.py). On rate-limit / failure
            # `pricing_tiers` is left empty and the card falls back to
            # "Price TBC" linking to /pages/fees.
            "pricing_tiers": self._fees_via_vision(),
            # Parsed from /pages/Late-Abstracts content below.
            "abstract_open": False,
            "abstract_deadline": None,
            "abstract_deadline_note": None,
            "is_sold_out": False,
        }

        # ---- Abstract submission status from /pages/Late-Abstracts -----
        # Look for an explicit closed-state phrase first, then a deadline date.
        abs_chunk = ""
        for chunk in combined_text_parts:
            if "abstract" in chunk.lower() and (
                "deadline" in chunk.lower() or "submission" in chunk.lower()
            ):
                abs_chunk = chunk
                break
        if abs_chunk:
            deadline_iso = self._parse_abstract_deadline(abs_chunk)
            if deadline_iso:
                result["abstract_deadline"] = deadline_iso
                # Validate against today — never claim open with a past deadline.
                from datetime import date as _date
                if deadline_iso >= _date.today().isoformat():
                    # Also check for explicit "closed" wording — wins over the date.
                    if re.search(
                        r"\b(submissions?\s+(?:are\s+)?(?:now\s+)?closed|closing\s+date\s+has\s+passed|abstract\s+submission(?:s)?\s+(?:is\s+|are\s+)?closed)\b",
                        abs_chunk, re.I,
                    ):
                        result["abstract_open"] = False
                    else:
                        result["abstract_open"] = True
                else:
                    result["abstract_open"] = False
            else:
                # No date parsed — only set abstract_open if explicitly stated open
                if re.search(
                    r"\b(submissions?\s+(?:are\s+)?(?:now\s+)?open|abstracts?\s+(?:are\s+)?(?:now\s+)?being\s+accepted)\b",
                    abs_chunk, re.I,
                ):
                    result["abstract_open"] = True
                    result["abstract_deadline_note"] = "see Late Abstracts page"

        # Soft fields — LLM-driven description with heuristic fallback
        result.update(self._extract_soft_fields(page, shell, llm_call,
                                                pre_text=combined_text[:5000]))
        # Force specialty — this is THE radiology AI conference
        result["specialty"] = "Radiology"

        return result

    def _fees_via_vision(self) -> List[Dict[str, Any]]:
        """Download the fees-page image(s) and extract prices via vision LLM."""
        import httpx
        from vision import extract_pricing_from_images
        try:
            r = httpx.get(
                f"{self.BASE}/pages/fees",
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (MedConf scraper)"},
            )
            r.raise_for_status()
            html = r.text
        except Exception as e:
            logger.warning(f"RCR AI Conference fees fetch failed: {e}")
            return []
        # Find candidate fee images — exclude branding / logo assets
        img_urls: List[str] = []
        for m in re.finditer(r'<img[^>]*src=["\'](.*?)["\']', html, re.I):
            src = m.group(1).strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = "https://rcraiconference.com" + src
            if not src.lower().startswith("http"):
                continue
            # Skip obvious branding / icon assets
            sl = src.lower()
            if any(k in sl for k in ("logo", "brand/", "icon", "favicon", ".svg")):
                continue
            # Prefer idloom.events documents (the actual fee tables) over
            # decorative .webp / .png hero images
            img_urls.append(src)
        # Heuristic: keep the largest image-document group (idloom documents
        # are uploaded as the actual fee tables)
        idloom = [u for u in img_urls if "idloom.events/document/" in u]
        candidates = idloom if idloom else img_urls
        if not candidates:
            return []
        logger.info(f"RCR AI Conference: sending {len(candidates)} fee image(s) to vision LLM")
        tiers = extract_pricing_from_images(candidates)
        logger.info(f"RCR AI Conference: vision returned {len(tiers)} tier(s)")
        return tiers

    _MONTHS_BY_NAME = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }

    def _parse_abstract_deadline(self, text: str) -> Optional[str]:
        """Return ISO date string for the abstract submission deadline if found."""
        # Match "Thursday, 26 March 2026" or "26 March 2026" or "26/03/2026"
        m = re.search(
            r"(?:\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b,?\s+)?"
            r"\b(\d{1,2})\s+([a-z]+)\s+(20\d{2})\b",
            text, re.I,
        )
        if m:
            day, mon_str, year = m.group(1), m.group(2).lower(), m.group(3)
            mon = self._MONTHS_BY_NAME.get(mon_str) or self._MONTHS_BY_NAME.get(mon_str[:3])
            if mon:
                return f"{int(year):04d}-{mon:02d}-{int(day):02d}"
        m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
        if m:
            try:
                return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
            except ValueError:
                pass
        return None

    def _first_cpd_from(self, text: str) -> Optional[int]:
        m = re.search(r"(\d{1,3})\+?\s*CPD\s*(?:credits?|points?)?", text, re.I)
        if not m:
            m = re.search(r"earn\s+over\s+(\d{1,3})", text, re.I)
        return int(m.group(1)) if m else None

    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
        pre_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = pre_text or ""
        title = shell.get("title") or "RCR Global AI Conference 2026"

        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (likely Radiology)" or null
}}"""

        result: Dict[str, Any] = {}
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
                raw = m.group(0)
            try:
                parsed = json.loads(raw)
                result["description"] = parsed.get("description")
            except json.JSONDecodeError as e:
                logger.warning(f"RCR AI Conference soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("description") and text:
            chunk = text[:320].rstrip()
            cut = chunk.rfind(". ")
            if cut > 100:
                chunk = chunk[: cut + 1]
            else:
                chunk = chunk + "…"
            # Append a pointer to where prices live
            chunk += " Registration fees published on /pages/fees."
            result["description"] = chunk

        return result


# ============================================================================
# Source 12 — my.rcr.ac.uk events portal (Salesforce LWC)
# ============================================================================

# Month abbreviations as used by Salesforce UK locale ("Sept" not "Sep")
_RCR_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _normalise_title(title: str) -> str:
    """Case-folded, punctuation-stripped key for lookup-by-title stability."""
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def _title_hash(title: str) -> str:
    return hashlib.sha256(_normalise_title(title).encode()).hexdigest()[:16]


def _synthetic_url(title: str) -> str:
    """Stable identity URL when we haven't captured the real one yet."""
    return f"https://my.rcr.ac.uk/event/by-title/{_title_hash(title)}"


def _parse_rcr_datetime(text: str) -> tuple[Optional[str], Optional[str]]:
    """Parse 'Tue, 16 Sept 2025, 13:00' → ('2025-09-16', '13:00')."""
    text = (text or "").strip()
    m = re.search(
        r"\b\d{1,2}\b\s+([A-Za-z]+)\s+(20\d{2})\s*,\s*(\d{1,2}):(\d{2})",
        text,
    )
    if not m:
        # Try without the day-of-week prefix
        m = re.search(
            r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})",
            text,
        )
        if m:
            day, mon_str, year = m.group(1), m.group(2).lower(), m.group(3)
            mon = _RCR_MONTHS.get(mon_str) or _RCR_MONTHS.get(mon_str[:3])
            if mon:
                return f"{int(year):04d}-{mon:02d}-{int(day):02d}", None
        return None, None
    # Capture day separately
    day_m = re.search(r"\b(\d{1,2})\s+" + re.escape(m.group(1)), text)
    if not day_m:
        return None, None
    day = day_m.group(1)
    mon_str = m.group(1).lower()
    year = m.group(2)
    time = f"{m.group(3).zfill(2)}:{m.group(4)}:00"
    mon = _RCR_MONTHS.get(mon_str) or _RCR_MONTHS.get(mon_str[:3])
    if not mon:
        return None, None
    return f"{int(year):04d}-{mon:02d}-{int(day):02d}", time


class RCREventsPortalExtractor(BaseExtractor):
    """my.rcr.ac.uk events portal — Salesforce LWC scrape."""

    SOURCE_ID = 12
    LISTING_URL = "https://my.rcr.ac.uk/event/acem__Event__c/Default?sort=Asc"

    # ------------------------------------------------------------------ #
    # Listing override — shadow DOM walk + click-each-new-tile
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Reuse the scraper's existing browser instance (set by AgentLoop
        # before calling us) — starting a second sync_playwright would
        # collide with the one already running on `self.browser`.
        br = getattr(self, "browser", None)
        if br is None or br.page is None:
            logger.warning("RCR portal: no browser available; skipping")
            return None
        # Look up existing rows so we can short-circuit clicks for known events
        from database import supabase
        existing = (
            supabase.table("conferences")
            .select("source_url, conference_name")
            .eq("source_id", self.SOURCE_ID)
            .eq("archived", False)
            .execute()
            .data
            or []
        )
        known_by_hash: Dict[str, str] = {}
        for r in existing:
            name = r.get("conference_name") or ""
            url = r.get("source_url") or ""
            if not name:
                continue
            known_by_hash[_title_hash(name)] = url

        try:
            br.navigate(self.LISTING_URL)
            br.page.wait_for_timeout(15000)
            # Scroll a few times to trigger lazy load
            for _ in range(3):
                br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                br.page.wait_for_timeout(2000)

            # Harvest event tiles. RCR's Salesforce portal rewrote the LWC
            # in mid-2026: `.tile-item` no longer exists. Every event now
            # renders as an anchor `<a href="https://my.rcr.ac.uk/event/<id>">`
            # containing the title (usually in an <h*>) and a short snippet.
            # Walk the shadow DOM for those anchors, skipping the two nav
            # links whose href carries a `?redirect=` / `?_gl=` query string.
            tiles = br.page.evaluate(r"""() => {
                const EVENT_ID_RE = /\/event\/([A-Za-z0-9]{15,})/;
                function walk(root, acc) {
                    root.querySelectorAll('a[href*="/event/"]').forEach(a => acc.push(a));
                    root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot, acc); });
                }
                const acc = [];
                walk(document, acc);
                const seen = new Set();
                const out = [];
                for (const a of acc) {
                    const url = new URL(a.href, location.href);
                    if (url.search) continue;                       // nav links
                    const m = url.pathname.match(EVENT_ID_RE);
                    if (!m) continue;
                    const id = m[1];
                    if (seen.has(id)) continue;
                    seen.add(id);
                    const titleEl = a.querySelector('h1,h2,h3,h4,strong,b');
                    const rawTitle = titleEl ? titleEl.textContent.trim()
                        : a.textContent.replace(/\s+/g, ' ').trim().split(/(?<=\))\s|\.\s/, 1)[0];
                    out.push({
                        title: (rawTitle || '').trim(),
                        booking_url: url.origin + url.pathname,
                        text: a.textContent.replace(/\s+/g, ' ').trim().slice(0, 400),
                    });
                }
                return out.filter(t => t.title);
            }""") or []
            logger.info(f"RCR portal: harvested {len(tiles)} tiles")

            # Anchor already carries the /event/<id> URL — no more
            # click-to-capture round-trip needed. If a title matches an
            # existing DB row, keep the stored URL for stability.
            shells: List[Dict[str, Any]] = []
            seen_titles: set = set()
            for t in tiles:
                title = t["title"]
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                stored = known_by_hash.get(_title_hash(title))
                shells.append({
                    "title": title,
                    "booking_url": stored or t["booking_url"],
                    "category": None,
                    "_listing_snippet": t.get("text", ""),
                })
            return shells
        except Exception as e:
            logger.warning(f"RCR portal listing failed: {e}")
            return []

    def _click_and_capture(self, br, title: str, idx: int) -> Optional[str]:
        """Click the tile with given title; return the new URL or None."""
        try:
            br.navigate(self.LISTING_URL)
            br.page.wait_for_timeout(8000)
            # Scroll a bit so the target tile is rendered
            for _ in range(3):
                br.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                br.page.wait_for_timeout(1500)
            # Click the tile whose title matches
            br.page.evaluate(
                r"""(targetTitle) => {
                    function findTiles(root, acc) {
                        root.querySelectorAll('.tile-item').forEach(t => acc.push(t));
                        root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) findTiles(el.shadowRoot, acc); });
                    }
                    const acc = [];
                    findTiles(document, acc);
                    for (const t of new Set(acc)) {
                        const titleEl = t.querySelector('.tile-item__title');
                        const name = titleEl ? titleEl.textContent.trim() : '';
                        if (name === targetTitle) {
                            const inner = t.querySelector('a, button, [role=button]');
                            if (inner) inner.click(); else t.click();
                            return;
                        }
                    }
                }""",
                title,
            )
            br.page.wait_for_timeout(4500)
            url = br.page.url
            if "/event/" in url and "Default" not in url:
                # Strip tracking params
                return url.split("?")[0]
            return None
        except Exception as e:
            logger.warning(f"RCR click capture failed for {title!r}: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Detail extraction — body.innerText after JS render
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"conference_name": shell.get("title")}

        # Synthetic-URL shells haven't been captured yet — try once
        if "/by-title/" in (shell.get("booking_url") or ""):
            result["description"] = "Detail page URL pending capture; will retry on next scrape."
            result["specialty"] = "Radiology"
            return result

        # Wait for the LWC content to render
        try:
            page.wait_for_timeout(12000)
        except Exception:
            pass

        body = ""
        try:
            body = page.evaluate("() => document.body.innerText || ''") or ""
        except Exception as e:
            logger.warning(f"RCR detail body fetch failed: {e}")

        # Parse the section markers
        event_type = self._between(body, "Event type is", "Start and end date of the event")
        date_block = self._between(body, "Start and end date of the event", "Event description")
        description = self._between(body, "Event description", "Are you going?")

        # Dates
        if date_block:
            lines = [l.strip() for l in date_block.splitlines() if l.strip()]
            # Find lines containing a year — those are the date lines
            date_lines = [l for l in lines if re.search(r"20\d{2}", l)]
            if date_lines:
                start_date, start_time = _parse_rcr_datetime(date_lines[0])
                if start_date:
                    result["start_date"] = start_date
                if start_time:
                    result["start_time"] = start_time
                if len(date_lines) > 1:
                    end_date, _ = _parse_rcr_datetime(date_lines[-1])
                    if end_date:
                        result["end_date"] = end_date

        # Format from event_type field
        et_lower = (event_type or "").lower()
        if any(k in et_lower for k in ("zoom", "webinar", "virtual", "online")):
            result["event_format"] = "online"
        elif "hybrid" in et_lower:
            result["event_format"] = "hybrid"
        elif any(k in et_lower for k in ("in-person", "in person", "face-to-face")):
            result["event_format"] = "in_person"

        # Venue — if "Royal College of Radiologists, 63 Lincoln's Inn Fields"
        # appears after the description it's the venue address
        if "lincoln" in body.lower() or "63 lincoln" in body.lower():
            if result.get("event_format") != "online":
                result["venue_name"] = "Royal College of Radiologists, 63 Lincoln's Inn Fields"
                result["city"] = "London"
                result["region"] = "London"
                if "event_format" not in result:
                    result["event_format"] = "in_person"

        # Sold-out / waiting list / register state
        if re.search(r"\b(sold out|waiting list|fully booked|registration closed)\b", body, re.I):
            result["is_sold_out"] = True

        # Description (clean it)
        if description:
            desc = re.sub(r"\s+", " ", description).strip()
            # Strip trailing acknowledgements section if too long
            desc_truncated = desc[:600]
            if "acknowledg" in desc_truncated.lower():
                desc_truncated = desc_truncated.split("Acknowledgements")[0].strip()
            result["description"] = desc_truncated

        # Free events
        if re.search(r"free of charge|free to attend|complimentary", body, re.I):
            result["pricing_tiers"] = [{
                "tier_label": "Standard",
                "price_gbp": 0.0,
                "currency": "GBP",
                "is_early_bird": False,
                "early_bird_deadline": None,
            }]

        # Specialty — always Radiology for RCR
        result["specialty"] = self._infer_specialty(shell.get("title") or "")

        # Event type heuristic (course / workshop / conference)
        # Let the merge layer's title heuristic do its job; we just give it
        # a clean title.

        result["cpd_accredited"] = bool(re.search(r"\bcpd\b", body, re.I))

        return result

    def _between(self, text: str, start_marker: str, end_marker: str) -> str:
        """Extract text between two markers (case-insensitive)."""
        if not text:
            return ""
        # Case-insensitive split
        pat_start = re.escape(start_marker)
        pat_end = re.escape(end_marker)
        m = re.search(pat_start + r"(.*?)" + pat_end, text, re.S | re.I)
        return m.group(1).strip() if m else ""

    def _infer_specialty(self, title: str) -> str:
        """RCR covers two disciplines: Radiology and Clinical Oncology."""
        tl = (title or "").lower()
        if "oncolog" in tl:
            return "Clinical Oncology"
        return "Radiology"
