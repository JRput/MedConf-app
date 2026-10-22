"""NIHR (National Institute for Health and Care Research) events: UNVERIFIED placeholder, domain refuses us.

Status 2026-10-21: every URL on nihr.ac.uk (/events and the home page) answers HTTP 403 "ERROR: The request could not be
satisfied. Request blocked." (CloudFront) to curl with a browser User-Agent and to headless Chromium from a home IP; the
GitHub-runner probe of the same day got the same CloudFront refusal. No listing or detail HTML was ever seen, so NO
selector in this file has been tested. It is a constants-only subclass of the WordPress family so that a later wave can
pick it up if the block lifts. Do not register it active until the harness has run against real HTML.
"""
import re

from .wordpress_generic import WordPressGenericExtractor


class NihrExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.nihr.ac.uk/events"
    SOCIETY = "NIHR"
    DEFAULT_SPECIALTY = "Research"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    EVENT_LINK_RE = re.compile(r"^/events/[a-z0-9\-]+/?$", re.I)
