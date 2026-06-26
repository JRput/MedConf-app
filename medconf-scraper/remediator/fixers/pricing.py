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

logger = logging.getLogger(__name__)

_FREE_RE = re.compile(
    r"\b(?:free\s+(?:of\s+charge|to\s+attend|admission)|complimentary|no\s+(?:cost|fee)\s+to\s+attend)\b",
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
    "student", "associate",
)


def _text_pricing_sweep(page_text: str) -> List[dict]:
    """Find pricing rows in three patterns:
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

    def add(label: str, symbol: str, price_str: str) -> None:
        label = label.strip()[:200]
        if not label or len(label) < 3:
            return
        try:
            price = float(price_str.replace(",", ""))
        except ValueError:
            return
        if price <= 0 or price > 50000:
            return
        currency = {"£": "GBP", "$": "USD", "€": "EUR"}[symbol]
        key = (label.lower(), price)
        if key in seen_keys:
            return
        seen_keys.add(key)
        tiers.append({
            "tier_label": label,
            "price_gbp": price,
            "currency": currency,
            "is_early_bird": "early" in label.lower(),
            "early_bird_deadline": None,
        })

    # Pattern A & B — line-form
    for line in page_text.splitlines():
        line = line.strip()
        if "£" not in line and "$" not in line and "€" not in line:
            continue
        m = re.search(r"^(.*?)[|:]\s*([£$€])\s*([\d,]+(?:\.\d+)?)\s*$", line)
        if not m:
            m = re.search(r"^(.+?)\s+([£$€])\s*([\d,]+(?:\.\d+)?)\s*$", line)
        if not m:
            continue
        add(m.group(1), m.group(2), m.group(3))

    # Pattern C — inline "<label-word> £<amount>" within paragraphs. Many
    # WordPress / academic course sites flatten to one big line in
    # html→text conversion, so line patterns miss them. Anchor to a
    # KNOWN label word to avoid false positives like "page 1400" or
    # "in 1400 hours". Captures up to 3 leading words for context
    # (e.g. "Late registration £200").
    label_alt = "|".join(_PRICE_LABEL_WORDS)
    inline_rx = re.compile(
        rf"((?:[A-Za-z][A-Za-z-]{{2,30}}\s+){{0,3}}(?:{label_alt}))"
        r"\s*[:\-]?\s*"
        r"([£$€])\s*([\d,]+(?:\.\d+)?)",
        re.I,
    )
    for m in inline_rx.finditer(page_text):
        add(m.group(1), m.group(2), m.group(3))

    return tiers


def fix_pricing(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[List[dict]], Optional[str]]:
    source_url = row.get("source_url") or ""
    if not page_text and not source_url:
        return None, None

    # 1. Free event check
    if page_text and _FREE_RE.search(page_text):
        return [{
            "tier_label": "Standard",
            "price_gbp": 0.0,
            "currency": "GBP",
            "is_early_bird": False,
            "early_bird_deadline": None,
        }], "free_event"

    # 2. Text regex sweep on the page itself
    tiers = _text_pricing_sweep(page_text or "")
    if tiers:
        return tiers, "text_regex"

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

    image_urls: List[str] = []
    for fees_url in fees_urls:
        try:
            r = httpx.get(fees_url, timeout=20, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (MedConf remediator)"})
            if r.status_code >= 400:
                continue
            html = r.text
        except Exception:
            continue
        # Try text regex on the fees page too
        from urllib.parse import urlparse
        clean = re.sub(r"<[^>]+>", " ", html)
        clean = re.sub(r"\s+", " ", clean).strip()
        tiers = _text_pricing_sweep(clean)
        if tiers:
            return tiers, "text_regex_fees_page"
        # Collect image URLs for vision LLM
        image_urls.extend(_find_fee_image_urls(html, fees_url))

    # 4. Vision LLM on collected images
    if image_urls:
        try:
            from vision import extract_pricing_from_images
            tiers = extract_pricing_from_images(image_urls)
            if tiers:
                return tiers, "vision_llm"
        except Exception as e:
            logger.warning(f"remediator: vision pricing failed: {e}")

    return None, None
