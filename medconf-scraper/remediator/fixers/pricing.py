"""Pricing fixer — text regex + vision LLM for image-based fees.

Returns list of pricing_tier dicts ready for insertion via
database.insert_pricing_tiers. Or returns None if no pricing extractable.

The "free event" case — body explicitly says "free of charge" — produces
a single £0 tier so the card shows "Free" rather than "Price TBC".
"""

from __future__ import annotations
import logging
import re
from typing import Callable, List, Optional, Tuple

import httpx

import money

from remediator.signals import NON_FEE_CONTEXT_RE, free_phrase_context, price_text_signal

logger = logging.getLogger(__name__)

# "complimentary" alone is NOT enough: SCCM's shared calendar page says
# "Registered attendees receive complimentary access to the webcast" about one
# unrelated event, which marked 67 paid events free (2026-10-04).
_FREE_RE = re.compile(
    r"\b(?:free\s+(?:of\s+charge|to\s+attend|admission)|"
    r"complimentary\s+(?:registration|admission|entry|attendance|tickets?)|"
    r"no\s+(?:cost|fee)\s+to\s+attend)\b",
    re.I,
)


def _find_fee_image_urls(html: str, page_url: str) -> List[str]:
    """Extract candidate fee-table image URLs from a fees-page HTML.

    Filters out logos / icons / SVGs."""
    from urllib.parse import urljoin
    urls: List[str] = []
    for m in re.finditer(r'<img[^>]*src=["\'](.*?)["\']', html, re.I):
        src = m.group(1).strip()
        if src.startswith("//"):
            src = "https:" + src
        elif not src.lower().startswith("http"):
            src = urljoin(page_url, src)
        sl = src.lower()
        if any(k in sl for k in ("logo", "/brand/", "icon", "favicon", ".svg")):
            continue
        urls.append(src)
    return urls


_PRICE_LABEL_WORDS = (
    "cost", "fee", "fees", "tuition", "price", "rate", "rates",
    "members?", "non[- ]members?", "standard", "early[- ]bird",
    "late", "charge", "registration", "ticket", "delegate",
    "consultant", "trainee", "resident", "junior", "senior",
    "student", "associate", "speaker", "listener", "poster", "participant", "attendee",
)


_VAT_TAIL_RE = re.compile(r"^\s*(?:\(|\+|plus\b|incl?\.?|excl?\.?|ex\.?|\-)?\s*(?:incl\w*\.?\s+|excl\w*\.?\s+)?(?:VAT|GST|tax)\b", re.I)


def _text_pricing_sweep(page_text: str) -> List[dict]:
    """Find pricing rows in three patterns (amounts read by `money.find_amounts`:
    symbol or ISO-code, prefix or suffix, "1.500,00 €", "S$465"; a tier whose
    currency the text does not state is dropped, never defaulted):
       - Line A: "Label | £100.00"
       - Line B: "Label £100.00" (label and price on same line)
       - Inline C: "...Cost £1400 ..." (label-word immediately before
         price within a longer text block, used for sites that flatten
         to one line e.g. Royal Marsden School module pages)
    """
    if not page_text:
        return []
    tiers: List[dict] = []
    seen_keys: set = set()

    def add(label: str, mny) -> None:
        label = label.strip()[:200]
        if not label or len(label) < 3:
            return
        if NON_FEE_CONTEXT_RE.search(label):
            return  # cancellation / parking / deposit... is not a registration fee
        if mny.high is not None or not mny.currency:
            return  # a range is not one fee; no stated currency is never GBP
        price = mny.amount
        if price <= 0 or not money.plausible(price, mny.currency):
            return
        key = (label.lower(), price)
        if key in seen_keys:
            return
        seen_keys.add(key)
        tiers.append({
            "tier_label": label,
            "price_gbp": price,
            "currency": mny.currency,
            "is_early_bird": "early" in label.lower(),
            "early_bird_deadline": None,
        })

    # Pattern A & B — line-form: the line's single amount ends it (an optional
    # "+ VAT" note may follow) and everything before it is the label.
    for line in page_text.splitlines():
        line = line.strip()
        if not line or not re.search(r"\d", line):
            continue
        found = money.find_amounts(line)
        if len(found) != 1:
            continue
        mny = found[0]
        if line[mny.span[1]:].strip() and not _VAT_TAIL_RE.match(line[mny.span[1]:]):
            continue
        add(line[:mny.span[0]].rstrip(" \t|:-\u2013\u2014"), mny)

    # Pattern C — inline "<label-word> £<amount>" within paragraphs. Many
    # WordPress / academic course sites flatten to one big line in
    # html→text conversion, so line patterns miss them. Anchor to a
    # KNOWN label word to avoid false positives like "page 1400" or
    # "in 1400 hours". Captures up to 3 leading words for context
    # (e.g. "Late registration £200").
    label_alt = "|".join(_PRICE_LABEL_WORDS)
    tail_rx = re.compile(
        rf"(?<![A-Za-z])((?:[A-Za-z][A-Za-z-]{{2,30}}[ \t]+){{0,3}}(?:{label_alt}))\s*[:\-]?\s*$",   # same-line words only: no label may span a line break
        re.I,
    )
    for mny in money.find_amounts(page_text):
        window = page_text[max(0, mny.span[0] - 80): mny.span[0]]
        m = tail_rx.search(window)
        if m:
            add(m.group(1), mny)

    return tiers


def fix_pricing(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[List[dict]], Optional[str]]:
    source_url = row.get("source_url") or ""
    if not page_text and not source_url:
        return None, None

    # 1. Text regex sweep FIRST: a page that shows fee amounts is never free.
    # (2026-10-18: ESMO ELCC/Breast 2027 were marked free because one table row
    # said "Press Representatives | Free of charge" beside nine EUR rows.)
    tiers = _text_pricing_sweep(page_text or "")
    if tiers:
        return tiers, "text_regex"

    # 2. Free event: only when a free phrase describes the whole event, the
    # page shows no currency amounts, and the phrase is not a table row /
    # single fee category (see signals.free_phrase_context).
    if page_text and _FREE_RE.search(page_text) and not price_text_signal(page_text):
        ctx = free_phrase_context(page_text, _FREE_RE)
        if ctx:
            logger.info("fix_pricing: free_event accepted for %s, matched line: %r",
                        source_url, ctx[:200])
            return [{
                "tier_label": "Standard",
                "price_gbp": 0.0,
                "currency": "GBP",
                "is_early_bird": False,
                "early_bird_deadline": None,
            }], "free_event"
        logger.info("fix_pricing: free wording rejected for %s (table row / category / no event context)",
                    source_url)

    # 3. Try fees sub-pages — only for source URL patterns we KNOW have them.
    # Salesforce LWC portals (my.rcr.ac.uk) and similar don't have sub-pages,
    # so we skip the URL-guessing dance there.
    NO_FEES_PAGE_DOMAINS = ("my.rcr.ac.uk", "engage.rcgp.org.uk")
    fees_urls = []
    if any(d in source_url for d in NO_FEES_PAGE_DOMAINS):
        pass  # skip — these portals have all info on the detail page
    elif "rcraiconference.com" in source_url:
        fees_urls.append(source_url.split("?")[0].rstrip("/") + "/pages/fees")
    elif "rcgpac" in source_url:
        fees_urls.append(source_url.rstrip("/") + "/tickets")
    elif "rcseng.ac.uk" in source_url or "rsm.ac.uk" in source_url:
        # These publish prices inline on the detail page
        pass
    else:
        # Generic flagship-subsite pattern — try common fee suffixes
        for suffix in ("/fees", "/fees-and-how-to-book", "/registration-and-fees"):
            fees_urls.append(source_url.split("?")[0].rstrip("/") + suffix)

    # Profiled 2026-10-03 (ACPGBI, source 37): this tier-1 path fetched each
    # guessed fees page with an uncached httpx.get and then sent EVERY
    # non-logo <img> on a 200 response to the vision model — bypassing the
    # explorer's image/time budgets, so a run kept making 60 s vision calls
    # long after "vision budget exhausted" was logged. It now shares the
    # explorer's cached/circuit-broken fetcher, the money-proximity image
    # filter, and the process-wide vision budgets.
    from remediator.explorer import (
        fetch_page_text_and_html, find_money_images, source_time_up, usable_vision_tiers,
        get_source_deadline,
        _note_vision_time,
    )
    image_urls: List[str] = []
    for fees_url in fees_urls:
        if source_time_up():
            break
        clean, html = fetch_page_text_and_html(fees_url)
        if not html:
            continue
        # Try text regex on the fees page too
        tiers = _text_pricing_sweep(clean or "")
        if tiers:
            return tiers, "text_regex_fees_page"
        # Collect image URLs for vision LLM (budgeted + money-proximity filtered)
        image_urls.extend(find_money_images(html, fees_url, limit=6))

    # 4. Vision LLM on collected images
    if image_urls:
        try:
            import time as _t
            from vision import extract_pricing_from_images
            _t0 = _t.time()
            tiers = usable_vision_tiers(extract_pricing_from_images(image_urls, stop_at=get_source_deadline()))
            _note_vision_time(_t.time() - _t0)
            if tiers:
                return tiers, "vision_llm"
        except Exception as e:
            logger.warning(f"remediator: vision pricing failed: {e}")

    return None, None
