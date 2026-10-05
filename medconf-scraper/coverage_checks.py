"""Pre-registration coverage checks for a NEW source (PLAYBOOK "Coverage checklist").

Pure, no network, no DB. Takes the merged event the harness built plus the
rendered detail page and reports the miss patterns the owner has found on
live sources, so they are caught before a source is registered. All detectors
are imported from the audit / explorer / image_scan / abstract_classifier /
validator modules; nothing is re-implemented here except the small N-day
wording regex and the tier-list comparisons.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

PRICE_CODES = ("PRICE_TEXT_ON_PAGE", "PRICE_IMAGE_ON_PAGE", "PRICE_EXTERNAL_LINK", "PRICE_SAME_SITE_LINK")
SUBMISSION_CODES = ("SUBMISSION_NO_DEADLINE",)
BLOCKING_PREFIXES = ("PRICE_", "SUBMISSION_")

_NDAY_RE = re.compile(
    r"\b(?:(?:two|three|four|five|six|seven|2|3|4|5|6|7)[\s-]*day|"
    r"(?:2|3|4|5|6|7)\s*days)\b", re.I)


@dataclass
class Warning:
    code: str
    message: str
    evidence: str = ""

    def __str__(self) -> str:
        return f"{self.code}: {self.message}" + (f" [{self.evidence}]" if self.evidence else "")


def is_blocking(w: Warning) -> bool:
    return w.code.startswith(BLOCKING_PREFIXES)


# Account / newsletter sign-up, not registration for THIS event.
_ACCOUNT_LINK_RE = re.compile(
    r"register\s+(?:as|for\s+(?:an?\s+)?(?:account|updates?|newsletter|alerts?|interest))|register\s+your\s+interest|"
    r"create\s+(?:an?\s+)?account|sign[\s-]?up|log\s?in|sign[\s-]?in|my\s+account|subscribe|join\s+(?:us|now|the)|"
    r"become\s+a\s+member|membership", re.I)
_ANCHOR_HREF_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\']', re.I)


def event_registration_links(html: str, base_url: str, listing_html: str = "") -> list:
    """Same-site registration links that are about THIS event: the explorer's
    picker, run on the page with nav/header/footer/aside removed, minus links
    that also appear on the listing page (site chrome) and account/newsletter
    sign-up links. Coverage-only; the explorer keeps nav links on purpose."""
    from urllib.parse import urljoin
    from remediator.explorer import _CHROME_BLOCK_RE, find_registration_links
    body = _CHROME_BLOCK_RE.sub(" ", html or "")
    chrome = set()
    if listing_html:
        for h in _ANCHOR_HREF_RE.findall(listing_html):
            chrome.add(urljoin(base_url, h).split("#")[0].split("?")[0].rstrip("/"))
    out = []
    for url, text in find_registration_links(body, base_url, limit=10):
        if _ACCOUNT_LINK_RE.search(text) or _ACCOUNT_LINK_RE.search(url.replace("-", " ").replace("_", " ")):
            continue
        if url.rstrip("/") in chrome:
            continue
        out.append((url, text))
    return out[:3]


def _own_text(html: str, text: str) -> str:
    """Page text without anchors and nav/header/footer/aside blocks, so "2 Day"
    in a link to a different course (Resus e-ALS -> ALS 2 Day) is not read as
    this event's length. Falls back to the plain text when no HTML is given."""
    if not html:
        return text
    from remediator.explorer import _CHROME_BLOCK_RE
    h = _CHROME_BLOCK_RE.sub(" ", html)
    h = re.sub(r"<a\b[^>]*>.*?</a\s*>", " ", h, flags=re.I | re.S)
    return re.sub(r"<[^>]+>", " ", h)


def run_coverage_checks(merged_event: dict, page_html: str, page_text: str, base_url: str,
                        listing_html: str = "") -> List[Warning]:
    ev = merged_event or {}
    html, text = page_html or "", page_text or ""
    base_url = base_url or ev.get("booking_url") or ev.get("source_url") or ""
    out: List[Warning] = []
    tiers = ev.get("pricing_tiers") or []

    # 1. multi-day collapsed to one day
    start, end = ev.get("start_date"), ev.get("end_date")
    if start and (not end or end == start):
        from remediator.audit import DATE_RANGE_RE
        m = DATE_RANGE_RE.search(text) or _NDAY_RE.search(_own_text(html, text))
        if m:
            out.append(Warning("SINGLE_DAY_SUSPECT",
                               "end_date equals start_date but the page shows a multi-day range or wording",
                               m.group(0)))

    # 2-5. fees missing
    if not tiers:
        from remediator.audit import FREE_EVENT_RE, price_text_signal
        free = bool(FREE_EVENT_RE.search(text.lower()))
        if not free and price_text_signal(text):
            m = re.search(r"[£$€]\s*\d+[^\n]{0,40}", text)
            out.append(Warning("PRICE_TEXT_ON_PAGE", "no tiers but the page shows currency amounts",
                               m.group(0) if m else ""))
        if not free:
            try:
                from remediator.image_scan import fee_image_signal
                img = fee_image_signal(html, base_url)
                if img is not None:
                    out.append(Warning("PRICE_IMAGE_ON_PAGE", "no tiers but a fee/registration heading is followed by an image",
                                       f"heading {img.heading!r} image {img.label()}"))
            except Exception:
                pass
            from remediator.explorer import find_external_event_links
            reg = event_registration_links(html, base_url, listing_html)
            if reg:
                out.append(Warning("PRICE_SAME_SITE_LINK", "no tiers but the page links to a same-site registration/fees page",
                                   "; ".join(f"{t} -> {u}" for u, t in reg)))
            ext = find_external_event_links(html, base_url)
            if ext:
                out.append(Warning("PRICE_EXTERNAL_LINK", "no tiers but the page links to an external registration/event site",
                                   "; ".join(f"{t} -> {u}" for u, t in ext)))

    # 6. submission programme without a deadline/note
    if not ev.get("abstract_deadline") and not ev.get("abstract_deadline_note"):
        from extractors.abstract_classifier import has_submission_programme
        if has_submission_programme(text):
            out.append(Warning("SUBMISSION_NO_DEADLINE",
                               "page advertises a call for papers / submission programme but no deadline or note is set"))

    # 9. venue/city on the page but not stored
    if (not (ev.get("city") or "").strip() and not (ev.get("venue_name") or "").strip()
            and (ev.get("event_format") or "").lower() in ("in_person", "hybrid")):
        from extractors.location_evidence import find_location_evidence
        loc = find_location_evidence(html, text)
        if loc:
            out.append(Warning("LOCATION_ON_PAGE", "page names a venue/city but none stored", loc))

    # 7-8. tier list hygiene
    from validator import CTA_PREFIX_RE
    seen, dup = set(), []
    for t in tiers:
        label = str(t.get("tier_label") or "")
        if CTA_PREFIX_RE.search(label.strip()):
            out.append(Warning("CTA_IN_TIER_LABEL", "call-to-action text in tier label", label))
        key = (re.sub(r"s$", "", label.strip().lower()), t.get("price_gbp"), t.get("currency") or "GBP")
        if key in seen:
            dup.append(label)
        seen.add(key)
    if dup:
        out.append(Warning("DUPLICATE_TIERS", "same label and price appears more than once", "; ".join(dup)))
    return out


def location_on_linked_pages(merged_event: dict, current_url: str, fetch, already_found: bool = False) -> List[Warning]:
    """Pattern 9 when the event row has no city/venue and the detail page itself
    has no location evidence: look at the event's own booking/organiser site
    (ACEP: the master-calendar page has none, the chapter microsite names the
    venue). `fetch(url) -> (html, text)` is injected so this stays testable;
    the harness passes a browser fetch. At most two pages are fetched."""
    ev = merged_event or {}
    if already_found or (ev.get("city") or "").strip() or (ev.get("venue_name") or "").strip():
        return []
    if (ev.get("event_format") or "").lower() not in ("in_person", "hybrid"):
        return []
    from extractors.location_evidence import find_location_evidence
    seen = {(current_url or "").split("#")[0]}
    for key in ("booking_url", "organiser_url"):
        u = (ev.get(key) or "").split("#")[0]
        if not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        try:
            h, t = fetch(u)
        except Exception:
            continue
        loc = find_location_evidence(h or "", t or "")
        if loc:
            return [Warning("LOCATION_ON_PAGE", f"linked {key} page names a venue/city but none stored", f"{u} :: {loc}")]
    return []
