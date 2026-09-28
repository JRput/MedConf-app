"""
Medical Defence Union (MDU) — "Learn and develop" extractor.

The recon record for this source said "parked" / Incapsula-blocked, but that
was stale: `self.browser.navigate()` clears themdu.com on the first try,
every time, with the default profile — no challenge observed in ~30 loads
during development (2026-09-29). No special Cloudflare handling needed here.

There is no `/events` page (404) — the recon `start_url` was a guess. The
real hub is `/learn-and-develop`, which links to three separate things:
  - `/learn-and-develop/webinars` — a marketing page. All but one entry are
    past "Video and podcast" on-demand recordings (no future date, no MDU
    detail page — the on-demand ones aren't even hosted here). The one
    genuinely upcoming webinar has no MDU-hosted detail page either: its
    "Register here" link goes straight to an external ON24 URL with no
    dates/fees/venue for us to extract. Skipped — nothing extractable.
  - `/learn-and-develop/hospital-based-seminars` — a fixed menu of ~10 topics
    delivered on request ("Enquire now"); no scheduled dates at all. Skipped.
  - `/learn-and-develop/course-listing/<slug>` — dated, priced CPD courses
    ("course" tag). THIS is what we scrape.

The course-listing INDEX page itself renders almost empty client-side (just
breadcrumb + footer) even after a long wait — it's driven by a search widget
that only calls its API once you type/filter. Rather than fight that widget,
we call the same JSON API it calls directly:

    GET /api/v1/search/global?mainTag=learnAndDevelopPage&contentTypeAliases=eventPage
        &category=&query=&sort=Group&pageSize=200&page=1

This lists everything under Learn & Develop tagged `parent`: "E-learning"
(self-paced modules, no date — always skip, this is the "on-demand with no
dated events" case the brief asks us to flag), "Course" (what we want), and
a handful of untagged nav/category rows (`parent: ""`). Confirmed 2026-09-29:
51 total results, 8 "Course", 3 of which have an empty `dates` field (no
session currently scheduled — "Setting up in private practice", "Essential
communication skills", "Delivering difficult news with empathy" all show
"No dates available" on their own detail page) and are skipped; the other 5
have one or more `DD/MM/YYYY` dates in a comma-separated string — these are
COURSE SESSIONS, not separate courses (e.g. "Managing conflict with
colleagues" → 29/09/2026 (sold out) + 24/11/2026 (bookable), same course,
same fee). One parent + `sessions[]` per PLAYBOOK.md's course-type pattern.

The API payload is listing-only (title, price, nonmduprice, points, dates,
description as HTML prose) and is used purely for discovery + the
listing-hash fast-skip; `extract_detail()` re-reads everything from the live
detail page, which is fully server-rendered (confirmed in page.content()
immediately, no extra client fetch) with this shape:

    <div class="course-info-tile-section">
      <div class="cpd-container">5 CPD credits</div>
      <div class="date-chip">…per-session date chips…</div>
      <div class="location-price">
        <div class="location"><span class="label">Locations</span><span>Virtual</span></div>
        <div class="prices">
          <div class="non-member"><span class="label">Non-member</span><span>£260</span></div>
          <div class="member"><span class="label">Member</span><span>£190</span></div>
        </div>
      </div>
    </div>
    <section class="rich-text-renderer">…prose <p>, then <h2>Who should attend?</h2>…</section>
    <div class="event-detail-page-event-detail-section"><h3>Dates</h3>
      <section class="course-booking-section">   <!-- one per session -->
        <div class="date-time"><h5>29/09/2026</h5><h6>09:00 to 16:30</h6></div>
        <div>Virtual</div>                        <!-- per-session location -->
        <button>Join the waiting list</button>
        <div class="sold-out-label">Sold out</div>  <!-- only when sold out -->
      </section>
      …
    </div>

Every course probed so far is a single flat fee for MDU members vs
non-members, applied to every session (no per-session pricing seen) — one
set of `session_id: None` tiers per PLAYBOOK.md. Every course probed is
"full-day" (duration "8h") and every session so far is "Virtual" (online);
the extractor still reads the location per-session in case an in-person one
turns up, but has no address to parse beyond that one word, so venue/city/
region stay None for anything that isn't literally "Virtual"/"Online" —
never invented.

First <p> of the rich-text block is always the CPD accreditation line
("Accredited by the Federation of the Royal Colleges…" / "Awaiting
accreditation by…") and the second is always the format sentence ("This is
a full-day virtual course."). Both are stripped out of the description
candidate — they're metadata, not prose a reader would want summarised.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .specialty_classifier import classify_specialty

BASE = "https://www.themdu.com"
SEARCH_API = (
    f"{BASE}/api/v1/search/global?mainTag=learnAndDevelopPage"
    "&contentTypeAliases=eventPage&category=&query=&sort=Group&pageSize=200&page=1"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_DETAIL_JS = r"""
() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const h1 = document.querySelector('h1');
  const cpdEl = document.querySelector('.cpd-container');
  const memberEl = document.querySelector('.prices .member .sub-heading-small, .prices .member span:last-child');
  const nonMemberEl = document.querySelector('.prices .non-member .sub-heading-small, .prices .non-member span:last-child');
  const locSpans = Array.from(document.querySelectorAll('.location-price .location span'));
  const locationText = locSpans.length > 1 ? clean(locSpans[1].textContent)
                        : (locSpans[0] ? clean(locSpans[0].textContent) : '');

  const sessions = Array.from(document.querySelectorAll('.course-booking-section')).map(sec => {
    const dateEl = sec.querySelector('.date-time h5');
    const timeEl = sec.querySelector('.date-time h6');
    const locEl = Array.from(sec.querySelectorAll('.content > div')).find(d => !d.querySelector('.date-time') && !d.classList.contains('date-time'));
    const cta = sec.querySelector('.cta-and-label-inner button, button');
    const soldOut = !!sec.querySelector('.sold-out-label');
    return {
      dateText: dateEl ? clean(dateEl.textContent) : '',
      timeText: timeEl ? clean(timeEl.textContent) : '',
      locationText: locEl ? clean(locEl.textContent) : '',
      ctaText: cta ? clean(cta.textContent) : '',
      soldOut: soldOut,
    };
  });

  const rich = Array.from(document.querySelectorAll('.rich-text-wrapper > div > *')).map(el => ({
    tag: el.tagName.toLowerCase(),
    text: clean(el.textContent),
  }));

  const metaDesc = document.querySelector('meta[name="description"]');

  return {
    title: h1 ? clean(h1.textContent) : '',
    cpdText: cpdEl ? clean(cpdEl.textContent) : '',
    memberPrice: memberEl ? clean(memberEl.textContent) : '',
    nonMemberPrice: nonMemberEl ? clean(nonMemberEl.textContent) : '',
    locationText: locationText,
    sessions: sessions,
    rich: rich,
    metaDescription: metaDesc ? clean(metaDesc.getAttribute('content')) : '',
  };
}
"""


def _strip_html(html: Optional[str]) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    import html as html_lib
    return _WS_RE.sub(" ", html_lib.unescape(text)).strip()


def _parse_ddmmyyyy(text: str) -> Optional[str]:
    text = (text or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if not m:
        return None
    d, mo, y = (int(g) for g in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _parse_start_time(time_text: str) -> Optional[str]:
    m = re.search(r"\b([0-2]?\d):([0-5]\d)\b", time_text or "")
    if not m:
        return None
    hh = int(m.group(1))
    return f"{hh:02d}:{m.group(2)}" if hh <= 23 else None


def _location_to_format(location_text: str) -> Dict[str, Any]:
    """"Virtual"/"Online" -> online; a real place -> in_person with that
    venue name; empty -> unknown (never invented)."""
    loc = (location_text or "").strip()
    if not loc:
        return {"event_format": None, "venue_name": None}
    if re.search(r"\b(virtual|online|webinar)\b", loc, re.I):
        return {"event_format": "online", "venue_name": None}
    if "hybrid" in loc.lower():
        return {"event_format": "hybrid", "venue_name": loc}
    return {"event_format": "in_person", "venue_name": loc}


class MDUExtractor(BaseExtractor):
    """Medical Defence Union — Learn & Develop dated courses (event_type='course')."""

    # ------------------------------------------------------------------ #
    # Listing — the search-widget's own JSON API, filtered to dated Courses
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        if browser is None:
            logger.warning("MDU: no BrowserController available")
            return None

        try:
            browser.navigate(SEARCH_API)
            raw = browser.page.evaluate("() => document.body.innerText || ''")
        except Exception as e:
            logger.warning(f"MDU: search API fetch failed: {e}")
            return None

        try:
            payload = json.loads(raw)
        except Exception as e:
            logger.warning(f"MDU: search API returned non-JSON: {e}")
            return None

        results = payload.get("results") or []
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen: set = set()

        for r in results:
            if (r.get("parent") or "").strip().lower() != "course":
                continue
            dates_raw = (r.get("dates") or "").strip()
            if not dates_raw:
                # "No dates available" on the page — a course with no
                # scheduled session. Per brief: skip undated offerings
                # rather than invent a date.
                continue

            upcoming_dates = sorted(
                d for d in (
                    _parse_ddmmyyyy(part) for part in dates_raw.split(",")
                ) if d and d >= today
            )
            if not upcoming_dates:
                continue  # every session for this course has already run

            url = r.get("url") or ""
            if not url:
                continue
            booking_url = urljoin(BASE, url)
            if booking_url in seen:
                continue
            seen.add(booking_url)

            title = (r.get("title") or "").strip()
            desc_hint = (r.get("metaDescription") or "").strip() or _strip_html(r.get("description"))

            shells.append({
                "title": title,
                "booking_url": booking_url,
                "start_date": upcoming_dates[0],
                "event_type": "course",
                "description_hint": desc_hint[:400] or None,
                "is_sold_out": False,
            })

        logger.info(f"MDU: {len(shells)} dated courses from search API "
                    f"(of {sum(1 for r in results if (r.get('parent') or '').lower() == 'course')} Course entries)")
        return shells or None

    # ------------------------------------------------------------------ #
    # Detail
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        try:
            page.wait_for_selector("h1", timeout=15000)
            page.wait_for_timeout(800)
        except Exception:
            pass

        try:
            data = page.evaluate(_DETAIL_JS) or {}
        except Exception as e:
            logger.warning(f"MDU: detail parse failed for {url}: {e}")
            return {}

        result: Dict[str, Any] = {"event_type": "course", "abstract_open": False,
                                   "abstract_deadline": None, "is_sold_out": False}

        title = (data.get("title") or "").strip() or shell.get("title")
        if title:
            result["conference_name"] = title

        # --- sessions -------------------------------------------------
        today_iso = date.today().isoformat()
        sessions: List[Dict[str, Any]] = []
        for raw in data.get("sessions") or []:
            start_date = _parse_ddmmyyyy(raw.get("dateText") or "")
            if not start_date or start_date < today_iso:
                continue
            start_time = _parse_start_time(raw.get("timeText") or "")
            cta = (raw.get("ctaText") or "").strip().lower()
            if raw.get("soldOut"):
                avail = "sold_out"
            elif "waiting list" in cta:
                avail = "limited"
            elif "book" in cta:
                avail = "available"
            else:
                avail = "unknown"
            sess_loc = _location_to_format(raw.get("locationText") or data.get("locationText") or "")
            sessions.append({
                "start_date": start_date,
                "end_date": None,
                "start_time": start_time,
                "duration_text": raw.get("timeText") or None,
                "availability_status": avail,
                "spots_left": None,
                "booking_url": None,
                "venue_name": sess_loc.get("venue_name"),
                "notes": None,
            })

        sessions.sort(key=lambda s: s["start_date"])
        result["sessions"] = sessions

        if sessions:
            result["start_date"] = sessions[0]["start_date"]
        else:
            result["start_date"] = shell.get("start_date")

        # --- format / venue (course-level, from the summary location) --
        loc = _location_to_format(data.get("locationText") or "")
        result["event_format"] = loc.get("event_format")
        result["venue_name"] = loc.get("venue_name")
        result["city"] = None
        result["region"] = None

        # --- pricing (flat across all sessions) ------------------------
        tiers: List[Dict[str, Any]] = []
        member = self.parse_gbp(data.get("memberPrice") or "")
        non_member = self.parse_gbp(data.get("nonMemberPrice") or "")
        if member is not None:
            tiers.append({"tier_label": "Member", "price_gbp": member,
                          "session_id": None, "is_early_bird": False,
                          "early_bird_deadline": None})
        if non_member is not None:
            tiers.append({"tier_label": "Non-member", "price_gbp": non_member,
                          "session_id": None, "is_early_bird": False,
                          "early_bird_deadline": None})
        result["pricing_tiers"] = tiers

        # --- CPD ---------------------------------------------------------
        cpd_points = None
        m = re.search(r"(\d+)", data.get("cpdText") or "")
        if m:
            cpd_points = int(m.group(1))
        result["cpd_points"] = cpd_points or None

        rich = data.get("rich") or []
        rich_texts = [r.get("text", "") for r in rich if r.get("text")]
        accreditation_line = rich_texts[0] if rich_texts else ""
        if re.search(r"\baccredited by\b", accreditation_line, re.I):
            result["cpd_accredited"] = True
        elif re.search(r"\bawaiting accreditation\b", accreditation_line, re.I):
            result["cpd_accredited"] = False
        else:
            result["cpd_accredited"] = None

        # --- description / specialty (soft fields, deterministic backstop) --
        format_line_re = re.compile(r"^this is a (full|half)[- ]day\b", re.I)
        who_attend_idx = next(
            (i for i, r in enumerate(rich) if r.get("tag") in ("h2", "h3")
             and "who should attend" in (r.get("text") or "").lower()),
            len(rich),
        )
        body_paragraphs = [
            r.get("text", "") for r in rich[:who_attend_idx]
            if r.get("tag") == "p"
            and not re.search(r"\baccredited by\b|\bawaiting accreditation\b", r.get("text") or "", re.I)
            and not format_line_re.search(r.get("text") or "")
        ]
        fallback_description = " ".join(body_paragraphs).strip()
        if not fallback_description:
            fallback_description = shell.get("description_hint") or data.get("metaDescription") or None
        else:
            fallback_description = fallback_description[:600]

        description = fallback_description
        if body_paragraphs:
            prompt = (
                "Summarise this CPD course description in one or two plain "
                "sentences (max 50 words) for a directory card aimed at "
                "doctors. Return strict JSON: {\"summary\": \"...\"}. "
                "Text:\n" + " ".join(body_paragraphs)[:3000]
            )
            try:
                raw_resp = llm_call(prompt)
                if raw_resp:
                    parsed = json.loads(re.search(r"\{.*\}", raw_resp, re.S).group(0))
                    summary = (parsed.get("summary") or "").strip()
                    if summary:
                        description = summary
            except Exception as e:
                logger.warning(f"MDU: LLM description failed for {url}: {e}")
        result["description"] = description

        body_for_specialty = " ".join(body_paragraphs) or (fallback_description or "")
        result["specialty"] = classify_specialty(title, body_for_specialty)

        return result
