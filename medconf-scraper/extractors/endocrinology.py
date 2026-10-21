"""Society for Endocrinology (endocrinology.org) events: UNVERIFIED placeholder, domain blocked by Cloudflare.

Status 2026-10-21: every URL on endocrinology.org (pages, sitemap.xml) answers HTTP 403 with `cf-mitigated: challenge`
(a Cloudflare *managed* challenge) to curl and to headless Chromium, including `BrowserController.navigate()` with its
context rotation and a 60 s poll from a home IP; the title stays "Just a moment..." and the body never changes. No
listing or detail HTML was ever seen, so NO selector in this file has been tested. It is a constants-only subclass of the
WordPress family (the recon describes /events/ as a static Bootstrap page of ~11 event links with Bioscientifica / Cvent
registration) so that a later wave can pick it up if a cloud probe shows the challenge clears from a GitHub runner.
Do not register it until the harness has run against real HTML.

NOT the US Endocrine Society (source 77, `endocrine.py`).
"""
import re

from .wordpress_generic import WordPressGenericExtractor


class EndocrinologyExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.endocrinology.org/events/"
    SOCIETY = "Society for Endocrinology"
    DEFAULT_SPECIALTY = "Diabetes & Endocrinology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    EVENT_LINK_RE = re.compile(r"^/events/[a-z0-9\-]+/?$", re.I)
