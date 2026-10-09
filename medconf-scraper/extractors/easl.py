"""EASL (European Association for the Study of the Liver) events: WordPress family subclass.

Listing: Elementor loop cards under /what-we-do/events/ (rel=next pagination, 10 per page). Detail pages carry a
"Key Information" block (Location: City, Country / Dates:), no venue line, except microsites that have a
"Venue address:" block. Schools / Academy modules are applications (no fee). Flagship Congress fees live on
the external easlcongress.eu site: the "Register now" / "Visit the website" link is stored as organiser_url so
the explorer follows it.
"""
import re
from urllib.parse import urlparse

from .wordpress_generic import _COUNTRIES, WordPressGenericExtractor, dedupe_consecutive
from .tribe_events import clip_venue, html_to_lines

_TBC_RE = re.compile(r"^(?:tbc|tba|tbd|to be (?:announced|confirmed))$", re.I)
_COURSE_RE = re.compile(r"\b(?:School days|Academy days|About EASL Schools|EASL Schools of Hepatology|Guidelines Academy|Bootcamp)\b|\bMasterclass\b")
_EXT_LINK_RE = re.compile(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""")
_EXT_TEXT_RE = re.compile(r"^(?:register now|visit website|visit the website|register here)$", re.I)


class EaslExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://easl.eu/what-we-do/events/"
    SOCIETY = "EASL"
    DEFAULT_SPECIALTY = "Gastroenterology & Hepatology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    # cards live under /event/<slug>/ (not under the listing path); Elementor loop items open each card
    EVENT_LINK_RE = re.compile(r"^/event/[^/?#]+/?$")
    CARD_SPLIT_RE = re.compile(r'<div[^>]+class="elementor elementor-\d+ e-loop-item\b')

    def skip_event(self, shell):
        # "Talk Liver To Me" podcast episodes sit in the calendar with the podcast as their "location":
        # a release date for listen-on-demand audio, not an event anyone attends.
        return bool(re.search(r"podcast", shell.get("venue_raw") or "", re.I))

    def detail_from_html(self, html, shell, llm_call):
        out = super().detail_from_html(html, shell, llm_call)
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer|aside|form|template)\b.*?</\1\s*>", " ", html)))
        text = " ".join(lines)
        # location "TBC" is not a virtual event (the base reads a TBC place as online-only)
        if _TBC_RE.match((shell.get("venue_raw") or "").strip()) and not (out.get("venue_name") or out.get("city")):
            out.pop("event_format", None)
        if _COURSE_RE.search(text) or re.search(r"\b(?:school|academy|bootcamp|masterclass)\b", shell.get("title") or "", re.I):
            out["event_type"] = "course"
        # microsite pages: "Venue address:" then the venue name on the next line
        if not out.get("venue_name"):
            for i, ln in enumerate(lines[:-1]):
                if re.match(r"^Venue(?: address)?\s*:?$", ln, re.I):
                    nxt = lines[i + 1].strip()
                    if 4 <= len(nxt) <= 80 and not re.match(r"^\d", nxt) and not re.search(r"\bwill take place\b", nxt):
                        out["venue_name"] = clip_venue(nxt)
                        break
        v = out.get("venue_name")
        if v and "," in v:                                    # "Estrel Hotel Berlin, Sonnenallee 225,12057 Berlin, Germany" -> name only
            keep = []
            for part in (p.strip() for p in v.split(",")):
                if re.search(r"\d", part):
                    break
                keep.append(part)
            out["venue_name"] = ", ".join(keep[:2]) or v
        if not (out.get("venue_name") or out.get("city")):   # "Denver, CO, United States": city, state, country
            parts = [p.strip() for p in (shell.get("venue_raw") or "").split(",") if p.strip()]
            if len(parts) >= 3 and parts[-1] in _COUNTRIES:
                out["city"], out["region"] = parts[0], parts[-1]
                out["event_format"] = "in_person"
        # the organiser's own event site (Register now / Visit Website) -> organiser_url, fees are often there
        host = "easl.eu"
        for m in _EXT_LINK_RE.finditer(html):
            label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
            u = m.group(1).replace("&amp;", "&")
            h = urlparse(u).netloc.lower().removeprefix("www.")
            if _EXT_TEXT_RE.match(label) and h != host and not h.endswith("." + host):
                out["organiser_url"] = u
                break
        return out
