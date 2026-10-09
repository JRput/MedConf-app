"""BIA (British Infection Association) events: concrete5 site, family subclass.

`/education-events/infection-events` is a concrete5 `event_list` block: server-rendered cards
(`ccm-block-calendar-event-list-event`, title link `...?occurrenceID=N`, date "18 Nov 2026 - 22 Nov 2026"),
limited to 20 items per load (`data-page="20"`; the Load more control only appears past that, 8 events today).
Event pages are free prose: venue / format sit in sentences ("at Millennium Point in Birmingham",
"held in London and online", "| 12th October 2026 | 8:30am - 4:00pm | Holiday Inn, ..."), and registration and
fees live on external Fitwise / EventsAir or society sites, stored as `organiser_url`.
"""
import re
from typing import Any, Callable, Dict, List, Optional

from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, clip_venue, split_location

_UK_CITIES = {"London", "Birmingham", "Glasgow", "Edinburgh", "Manchester", "Liverpool", "Leeds", "Cardiff", "Bristol", "Newcastle", "Belfast", "Sheffield", "Nottingham", "Oxford", "Cambridge"}
_OWN_HOST = "britishinfection.org"
_LINK_RE = re.compile(r"""<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_SKIP_HOST_RE = re.compile(r"safelinks\.protection|facebook|linkedin|twitter|x\.com|youtube|instagram|mailto|google\.|bit\.ly|britishinfection", re.I)
_REG_TEXT_RE = re.compile(r"register|registration|book|here|website|find out more|visit", re.I)
_PROSE_VENUE_RES = [
    re.compile(r"\b(?:at|in)\s+(?:the\s+)?([A-Z][\w&' .-]{2,50}?)\s+in\s+([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b(?= on\b|[.,]| for\b)"),   # at Millennium Point in Birmingham on
    re.compile(r"\bat the\s+([A-Z]{2,}[\w ]*),\s+([A-Z][a-z]+),\s+(UK|United Kingdom)\b"),                                    # at the SEC, Glasgow, UK
]


class BiaExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.britishinfection.org/education-events/infection-events"
    SOCIETY = "BIA"
    DEFAULT_SPECIALTY = "Infectious Disease"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    EXTERNAL_LINKS = False

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        lines = html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html))
        title = shell.get("title") or ""
        idx = next((i for i, l in enumerate(lines) if l.strip() == title.strip()), 0)
        body = lines[idx + 1: idx + 14]
        text = " ".join(body)
        if not (out.get("venue_name") or out.get("city")):
            piped = next((l for l in body if "|" in l and re.search(r"20\d\d|\d(?:st|nd|rd|th)", l)), None)
            semi = re.search(r";\s*([A-Z][a-z]+),\s*([A-Z][\w &'-]{3,50}?)\s+(?:In-person|Online|Virtual)", text)
            if piped:                                              # "... | 12th October 2026 | 8:30am - 4:00pm | Holiday Inn, Birmingham Airport - NEC by IHG"
                seg = re.sub(r"\s*\([^)]*\)", "", piped.split("|")[-1]).strip()
                parts = [p.strip() for p in seg.split(",")]
                out["venue_name"] = clip_venue(parts[0])
                if len(parts) > 1:
                    cm = re.match(r"[A-Z][a-z]+(?: [A-Z][a-z]+)?", parts[1])
                    if cm and not re.search(r"\b(?:USA|US|UK)\b|[A-Z]{2}$", parts[1]):
                        out["city"] = cm.group(0)
                    elif re.search(r"\bUSA\b", parts[-1]):
                        out["region"] = "United States"
            elif semi:                                             # "7th-8th December; London, Royal College of Physicians In-person and virtual attendance"
                out["city"], out["venue_name"] = semi.group(1), semi.group(2).strip()
            else:
                for rx in _PROSE_VENUE_RES:
                    m = rx.search(text)
                    if m:
                        out["venue_name"], out["city"] = m.group(1).strip(), m.group(2).strip()
                        break
        if not out.get("city"):
            m = re.search(r"\b(?:held )?in ([A-Z][a-z]+) and online\b", text)
            if m:
                out["city"] = m.group(1)
        if re.search(r"\band online\b|\bhybrid\b|in-person and virtual", text, re.I) and (out.get("city") or out.get("venue_name")):
            out["event_format"] = "hybrid"
        elif (out.get("venue_name") or out.get("city")) and not out.get("event_format"):
            out["event_format"] = "in_person"
        elif not out.get("event_format") and re.search(r"\bonline\b|\bwebinar\b|\bvirtual\b", text[:400], re.I):
            out["event_format"] = "online"
        if out.get("city") and re.search(r"\sAirport|\s-\s", out["city"]):
            out["city"] = re.split(r"\s+(?:Airport|-)", out["city"])[0]        # "Birmingham Airport - NEC by IHG" -> Birmingham
        if out.get("city") in _UK_CITIES and not out.get("region"):
            out["region"] = "United Kingdom"
        # registration / fees are on an external site: keep it as organiser_url for the explorer
        for m in _LINK_RE.finditer(re.sub(r"(?is)<(nav|header|footer)\b.*?</\1\s*>", " ", html)):
            href, txt = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
            if _SKIP_HOST_RE.search(href) or _OWN_HOST in href:
                continue
            if _REG_TEXT_RE.search(txt) or "eventsair" in href:
                out["organiser_url"] = href
                break
        return out
