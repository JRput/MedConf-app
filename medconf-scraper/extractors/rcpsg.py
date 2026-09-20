# extractors/rcpsg.py
"""
Royal College of Physicians and Surgeons of Glasgow (RCPSG) — extractor.

Drupal 11 server-rendered site (rcpsg.ac.uk). Listing at /education paginates
via `?sort=earliest&page=1..N` (~10 cards/page). IMPORTANT: the listing shows
ONE CARD PER SCHEDULED SESSION, not one per course — a course with 3 upcoming
dates produces 3 cards all linking to the SAME /education/<slug> detail page.
`browser.get_event_cards()` also mis-detects the booking anchor
(community.rcpsg.ac.uk/event/book/...) as the per-card `booking_url`, which
would create N duplicate rows per course. We therefore override the listing
phase entirely (`list_shells_override`) to walk the paginated hub and dedupe
by the canonical /education/<slug> path.

Detail page structure (verified across 6 real pages)
------------------------------------------------------
- Canonical name: <h1> in the hero.
- Session dates: EITHER
    <select id="education-date"><option data-date="YYYY-MM-DD"
        data-location="..." data-url="community booking link"> ...
    (multiple upcoming sessions — course pattern), OR
    <input id="education-date" data-date="YYYY-MM-DD" data-location="..."
        data-url="..."> inside `.bp-hero-date`
    (exactly one upcoming session — conference/workshop pattern).
  Dates are already ISO (YYYY-MM-DD) in the data attribute — no month-name
  parsing needed.
- Venue/format: `#location-text` span (mirrors the selected option's
  data-location) OR the single date's data-location. "Online" means online;
  a "<venue>/Online" slash-joined value means hybrid; anything else is an
  in-person venue name (almost always an RCPSG-owned or Glasgow University
  building — "Glasgow" appears in the name itself in most cases).
- Pricing: prose fee text, in ONE of two spots —
    1. `.tab-content[data-id^="fees"]` — richer, e.g. "Members: £115",
       "Non-members: £220", "AHPs: £140", "Trainees: £130", "BSG: £120"
       (Glasgow Gastro Conference).
    2. `.course-register-block p` — simpler "Members £65.00. Non-members
       £105.00." summary that's always present when fees exist at all.
  Both are prose, not <table> markup, so pricing_tables.py's HTML-table
  parser doesn't apply here — we regex label/£amount pairs directly.
  Free events (e.g. Active Bystander Training) have NEITHER — 0 tiers is
  correct, not a bug.
- CPD: `.bp-hero-cpd-stars` text ("6 CPD") → regex fallback on body text.
- Description: `<h2>Overview</h2>` heading, walk siblings to next <h2>.
- Booking is via community.rcpsg.ac.uk (external registrar) — outbound
  only, never used as our canonical/detail URL.
"""

import re
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger


LISTING_BASE = "https://rcpsg.ac.uk/education"
MAX_LISTING_PAGES = 16  # observed 11 real pages; pad generously, stop early on empty page


def _clean_ws(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class RCPSGExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — dedupe by canonical /education/<slug> path since
    # the site renders one listing card PER SESSION, not per course.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Reuse the AgentLoop's already-launched browser when present
        # (llm_agent assigns self.browser before calling this). Launching a
        # second sync Playwright in the same thread throws — which previously
        # made this override silently fall back to the generic DOM walker,
        # whose cards point at community.rcpsg.ac.uk booking anchors (junk).
        own_browser = False
        b = getattr(self, "browser", None)
        if b is None or getattr(b, "page", None) is None:
            from browser import BrowserController
            b = BrowserController()
            b.launch()
            own_browser = True

        seen: Dict[str, Dict[str, Any]] = {}
        try:
            empty_streak = 0
            for p in range(1, MAX_LISTING_PAGES + 1):
                try:
                    b.navigate(f"{LISTING_BASE}?sort=earliest&page={p}")
                    b.page.wait_for_timeout(2500)
                    cards = b.page.evaluate(r"""() => {
                        return Array.from(document.querySelectorAll('a.hub-result-item-title')).map(a => {
                            const item = a.closest('.hub-result-item');
                            const desc = item ? item.querySelector('p') : null;
                            return {
                                href: a.href,
                                title: (a.textContent || '').trim(),
                                description_hint: desc ? (desc.textContent || '').trim() : null,
                            };
                        });
                    }""") or []
                except Exception as e:
                    logger.warning(f"RCPSG: listing page {p} failed: {e}")
                    cards = []

                if not cards:
                    empty_streak += 1
                    if empty_streak >= 2:
                        break
                    continue
                empty_streak = 0

                for c in cards:
                    href = c.get("href") or ""
                    if "/education/" not in href:
                        continue
                    path = href.split("?")[0].rstrip("/")
                    if path in seen:
                        continue
                    seen[path] = {
                        "title": c.get("title") or "",
                        "booking_url": path,
                        "is_sold_out": False,
                        "start_date": None,
                        "start_time": None,
                        "location_hint": None,
                        "description_hint": c.get("description_hint"),
                        "category": None,
                        "page_index": p,
                    }
        except Exception as e:
            # Do NOT fall back to the generic DOM walker — its cards link to
            # the community booking portal and produce data-less junk rows.
            # Fail the run honestly so it retries next night.
            raise RuntimeError(f"RCPSG listing override failed: {e}") from e
        finally:
            if own_browser:
                try:
                    b.close()
                except Exception:
                    pass

        shells = list(seen.values())
        if not shells:
            raise RuntimeError("RCPSG listing override found 0 shells — refusing generic-walker fallback")
        logger.info(f"RCPSG: {len(shells)} unique courses/events found across listing pages")
        return shells

    # ------------------------------------------------------------------ #
    # Detail extraction
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # 1. Canonical name from h1 (never trust shell title)
        try:
            h1 = page.evaluate("() => (document.querySelector('h1') || {}).textContent || ''")
        except Exception:
            h1 = ""
        result["conference_name"] = _clean_ws(h1) or shell.get("title")

        # 2. Session date(s) — either <select> (multi) or <input> (single)
        sessions_raw = self._extract_session_dates(page)

        # 3. Pricing (deterministic, flat across sessions — no evidence of
        # per-session variation on any probed page)
        result["pricing_tiers"] = self._extract_pricing(page)

        # 4. CPD
        result["cpd_points"], result["cpd_accredited"] = self._extract_cpd(page)

        # 5. Description + specialty
        overview_text = self._extract_overview_text(page)
        result.update(self._extract_soft_fields(page, shell, overview_text, llm_call))

        # 6. Dates / venue / sessions
        if len(sessions_raw) >= 2:
            # Course pattern — emit course_sessions
            sessions = []
            for s in sessions_raw:
                venue_fields = self._venue_from_location(s.get("location"))
                sessions.append({
                    "start_date": s["date"],
                    "end_date": None,
                    "start_time": None,
                    "duration_text": None,
                    "availability_status": "unknown",
                    "spots_left": None,
                    "booking_url": s.get("url"),
                    "notes": None,
                    **venue_fields,
                })
            result["event_type"] = "course"
            result["sessions"] = sessions

            today_iso = date.today().isoformat()
            upcoming = [s for s in sessions_raw if s["date"] and s["date"] >= today_iso]
            upcoming.sort(key=lambda s: s["date"])
            first = upcoming[0] if upcoming else sessions_raw[0]
            result["start_date"] = first["date"]
            result["end_date"] = None

            # Parent venue only if every upcoming session shares one location
            locs = {s.get("location") for s in (upcoming or sessions_raw) if s.get("location")}
            if len(locs) == 1:
                result.update(self._venue_from_location(next(iter(locs))))
            else:
                result["venue_name"] = None
                result["city"] = None
                result["region"] = None
                result["event_format"] = None
        elif len(sessions_raw) == 1:
            s = sessions_raw[0]
            result["start_date"] = s["date"]
            result["end_date"] = None
            result.update(self._venue_from_location(s.get("location")))
        else:
            # No date found at all — leave null, will retry next run per
            # the self-healing rule (event_format/venue null keeps re-fetching).
            result["start_date"] = shell.get("start_date")
            result["end_date"] = None
            result["venue_name"] = None
            result["city"] = None
            result["region"] = None
            result["event_format"] = None

        # 7. Abstract info — RCPSG courses don't run abstract submissions,
        # but scan anyway in case a conference (Glasgow Gastro etc.) has one.
        page_text = page.evaluate("() => document.body.textContent || ''")
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        return result

    # ------------------------------------------------------------------ #
    # Session dates — read the <select>/<input id="education-date"> widget
    # ------------------------------------------------------------------ #
    def _extract_session_dates(self, page: Page) -> List[Dict[str, Optional[str]]]:
        try:
            data = page.evaluate(r"""() => {
                const opts = Array.from(document.querySelectorAll('#education-date option'));
                if (opts.length) {
                    return opts.map(o => ({
                        date: o.getAttribute('data-date'),
                        location: o.getAttribute('data-location'),
                        url: o.getAttribute('data-url'),
                    }));
                }
                const inp = document.querySelector('input#education-date');
                if (inp) {
                    return [{
                        date: inp.getAttribute('data-date'),
                        location: inp.getAttribute('data-location'),
                        url: inp.getAttribute('data-url'),
                    }];
                }
                return [];
            }""") or []
        except Exception as e:
            logger.warning(f"RCPSG: session-date extraction failed: {e}")
            return []

        out: List[Dict[str, Optional[str]]] = []
        seen_dates = set()
        for d in data:
            iso = (d.get("date") or "").strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
                continue
            if iso in seen_dates:
                continue
            seen_dates.add(iso)
            out.append({
                "date": iso,
                "location": _clean_ws(d.get("location")) or None,
                "url": d.get("url") or None,
            })
        out.sort(key=lambda x: x["date"])
        return out

    # ------------------------------------------------------------------ #
    # Venue / city / region / format from a location string
    # ------------------------------------------------------------------ #
    _UK_REGIONS: Dict[str, str] = {
        "glasgow": "Scotland",
        "edinburgh": "Scotland",
        "aberdeen": "Scotland",
        "dundee": "Scotland",
        "inverness": "Scotland",
        "london": "London",
        "manchester": "North West England",
        "liverpool": "North West England",
        "leeds": "Yorkshire and the Humber",
        "newcastle": "North East England",
        "birmingham": "West Midlands",
        "bristol": "South West England",
        "cardiff": "Wales",
        "belfast": "Northern Ireland",
    }

    def _venue_from_location(self, location: Optional[str]) -> Dict[str, Any]:
        loc = (location or "").strip()
        if not loc:
            return {"venue_name": None, "city": None, "region": None, "event_format": None}

        loc_lower = loc.lower()
        has_online = "online" in loc_lower or "virtual" in loc_lower or "webinar" in loc_lower
        # Slash- or "and"-joined dual-mode value, e.g. "RCPSG/Online"
        physical_part = re.sub(r"\s*/\s*online\b|\bonline\b\s*/\s*", "", loc, flags=re.I).strip(" /")

        if has_online and physical_part and physical_part.lower() != loc_lower:
            event_format = "hybrid"
        elif has_online:
            return {"venue_name": None, "city": None, "region": None, "event_format": "online"}
        else:
            event_format = "in_person"
            physical_part = loc

        venue_name = physical_part[:200] if physical_part else None
        city = None
        region = None
        for key, reg in self._UK_REGIONS.items():
            if key in loc_lower:
                city = key.title()
                region = reg
                break
        return {
            "venue_name": venue_name,
            "city": city,
            "region": region,
            "event_format": event_format,
        }

    # ------------------------------------------------------------------ #
    # Pricing — prose "Label: £X" pairs from the fees tab or register block
    # ------------------------------------------------------------------ #
    _FEE_PAIR_RE = re.compile(
        r"([A-Za-z][A-Za-z /&\-]{0,40}?)\s*:?\s*£\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)"
    )

    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        try:
            blocks = page.evaluate(r"""() => {
                const out = [];
                const feesDiv = document.querySelector('.tab-content[data-id^="fees"]');
                if (feesDiv) out.push((feesDiv.textContent || '').replace(/\s+/g, ' ').trim());
                const regBlock = document.querySelector('.course-register-block p');
                if (regBlock) out.push((regBlock.textContent || '').replace(/\s+/g, ' ').trim());
                return out;
            }""") or []
        except Exception as e:
            logger.warning(f"RCPSG: pricing extraction failed: {e}")
            return []

        # Prefer the fees tab (richer) over the register-block summary; only
        # fall back to the second block if the first yielded nothing.
        tiers: List[Dict[str, Any]] = []
        for text in blocks:
            tiers = self._parse_fee_pairs(text)
            if tiers:
                break
        return tiers

    # Prose sentences ("The Diploma fee is £4,545...") produce grammatically
    # plausible but useless "labels" like "The Diploma Fee Is" or "You Will
    # Receive A". Real tier labels on this source are short nouns/roles
    # ("Members", "AHPs", "Trainees", "BSG"). Reject any match whose label
    # contains a filler/stopword or runs more than 3 words — these only
    # show up in free-text fee paragraphs (diplomas with payment-plan prose),
    # never in the genuine Member/Non-member tier lists.
    _LABEL_STOPWORDS = {
        "is", "will", "the", "a", "an", "you", "your", "this", "that",
        "having", "get", "receive", "and", "or", "for", "of", "in", "on",
        "to", "be", "have", "has", "having", "we", "our", "please",
        "approximately", "around", "due", "cost", "costs", "total", "from",
    }

    def _parse_fee_pairs(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        tiers: List[Dict[str, Any]] = []
        for m in self._FEE_PAIR_RE.finditer(text):
            label_raw = m.group(1).strip(" :.-")
            price_raw = m.group(2).replace(",", "")
            if not label_raw:
                continue
            words = label_raw.split()
            if len(words) > 3:
                continue
            if any(w.lower() in self._LABEL_STOPWORDS for w in words):
                continue
            try:
                price = float(price_raw)
            except ValueError:
                continue
            label = self._normalise_label(label_raw)
            tiers.append({
                "tier_label": label[:120],
                "price_gbp": price,
                "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                "early_bird_deadline": None,
            })

        # Dedupe by (label, price) — defends against responsive shadow copies
        seen = set()
        deduped = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(t)
        return deduped

    @staticmethod
    def _normalise_label(label: str) -> str:
        label = _clean_ws(label)
        # Common RCPSG tier words seen: Members, Non-members, AHPs, Trainees, BSG
        singular_map = {
            "members": "Member",
            "non-members": "Non-member",
            "non members": "Non-member",
            "trainees": "Trainee",
            "ahps": "AHP",
        }
        key = label.lower()
        if key in singular_map:
            return singular_map[key]
        # Title-case generic labels, but keep short all-caps acronyms (BSG etc.)
        if label.isupper() and len(label) <= 6:
            return label
        return " ".join(w if w.isupper() and len(w) <= 5 else w.capitalize() for w in label.split())

    # ------------------------------------------------------------------ #
    # CPD
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, page: Page) -> Tuple[Optional[int], bool]:
        try:
            hero_cpd = page.evaluate(
                "() => (document.querySelector('.bp-hero-cpd-stars') || {}).textContent || ''"
            )
        except Exception:
            hero_cpd = ""
        m = re.search(r"(\d+)\s*CPD", hero_cpd or "", re.I)
        if m:
            return int(m.group(1)), True

        text = page.evaluate("() => document.body.textContent || ''") or ""
        m = re.search(r"\b(\d+)\s*CPD\b", text, re.I)
        if m:
            return int(m.group(1)), True
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Overview section text (deterministic description source)
    # ------------------------------------------------------------------ #
    def _extract_overview_text(self, page: Page) -> str:
        try:
            text = page.evaluate(r"""() => {
                const heads = Array.from(document.querySelectorAll('h2'));
                const ov = heads.find(h => /^overview$/i.test((h.textContent || '').trim()));
                if (!ov) return '';
                let cursor = ov.nextElementSibling;
                let collected = '';
                let hops = 0;
                while (cursor && !/^H[1-6]$/.test(cursor.tagName) && hops < 12) {
                    collected += (cursor.textContent || '') + ' ';
                    cursor = cursor.nextElementSibling;
                    hops++;
                }
                return collected.replace(/\s+/g, ' ').trim();
            }""") or ""
        except Exception as e:
            logger.warning(f"RCPSG: overview extraction failed: {e}")
            return ""
        return text[:3000]

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM with deterministic fallbacks)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        overview_text: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        title = shell.get("title")

        if llm_call and overview_text:
            prompt = f"""You are summarising a single medical education event/course. Extract ONLY two fields.

EVENT TITLE: {title}

OVERVIEW TEXT:
{overview_text[:2500]}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the overview text" or null,
  "specialty": "primary clinical/topic area (e.g. Urology, Gastroenterology, Travel Medicine, Medical Education)" or null
}}"""
            raw = llm_call(prompt)
            if raw:
                import json
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
                    result["specialty"] = parsed.get("specialty")
                except Exception as e:
                    logger.warning(f"RCPSG soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Heuristic specialty backstop
        if not result.get("specialty"):
            heuristic = classify_specialty(title, overview_text or shell.get("description_hint"))
            if heuristic:
                result["specialty"] = heuristic

        # Description fallback — first sentence(s) of Overview text, then
        # listing card's description_hint if Overview was empty.
        if not result.get("description"):
            source_text = overview_text or shell.get("description_hint") or ""
            if len(source_text) > 40:
                result["description"] = self._truncate_to_sentence(source_text, 320)

        return result

    @staticmethod
    def _truncate_to_sentence(text: str, max_chars: int = 320) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        candidates = [cut.rfind(p + " ") for p in (".", "!", "?")]
        last_end = max(candidates)
        if last_end > max_chars * 0.5:
            return cut[: last_end + 1].rstrip()
        return cut.rstrip() + "…"
