"""BOA (British Orthopaedic Association) event & course calendar, on the Eventfolio platform (see ems_calendar.py).

`boa.ac.uk/learning-and-events/ems-event-calendar.html` is backed by the platform's JSON endpoint (see `ems_calendar.py`).
Rows are of three kinds, told apart by the badges on each card:
- BOA's own events (type badge Annual Congress / Training / Casting): always kept.
- "External" / "Non-BOA Event" rows (third-party courses and meetings): kept ONLY when relevant to orthopaedics (specialty classifier
  says Musculoskeletal & Trauma, or the title matches a small keyword list: trauma, spine, hand, foot & ankle, arthroplasty, fracture,
  bone, sports, surgery ...). The rest (a cardiology forum, a probiotics expo) are dropped and the count is logged. The "Go to event
  website" link of kept rows is stored as `organiser_url` for the fee explorer.
- on-demand / digital-access products ("Digital Access Only"): skipped, the live event is over.
The 2027 Annual Congress is not a calendar card: it is one line on /boa-annual-congress-2026/future-congresses.html
("2027 - 14th - 17th September, ACC Liverpool"), so it is read from there as one extra shell.
"""
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .ems_calendar import EmsCalendarExtractor, _MON_RE, _MONTHS, _UK_PLACES, _iso
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from .tribe_events import html_to_lines


# ── BOA ─────────────────────────────────────────────────────────────────────────────────────────

_FUTURE_CONGRESS_URL = "https://www.boa.ac.uk/boa-annual-congress-2026/future-congresses.html"
_CLINICAL_NOISE = {"Musculoskeletal & Trauma", "Surgery (General)", "Surgery (RCS)", "Leadership & Management", "Exam Preparation",
                   "Medical Education", "Research", "Wellbeing", "Faculty & Networking", "GP Training", "Telehealth",
                   "Primary Care AI / Digital", "Finance & Pensions", "General Practice", "Minor Surgery & Procedures"}
# One relevance regex for both uses: keeping third-party calendar rows and deciding the specialty label (orthogeriatric topics included).
_RELEVANT_RE = re.compile(r"(?i)orthop|trauma|musculoskeletal|\bmsk\b|\bspin(?:e|al)\b|\bhand\b|\bfoot\b|\bankle\b|arthroplasty|fracture|\bbones?\b|"
                          r"\bsports?\b|surgery|surgical|surgeon|\bknee\b|\bhip\b|shoulder|elbow|wrist|\bjoints?\b|cruciate|casting|plaster|ukite|cadaver|"
                          r"prehab\w*|\bfalls?\b|deconditioning|osteoporo\w*|frailty|rehabilitation|amputee|\blimb\b")


def is_third_party(card: Dict[str, Any]) -> bool:
    return "External" in (card.get("badges") or []) or (card.get("type") or "").lower().startswith("non-boa")


def is_relevant(title: str, category: str = "", teaser: str = "") -> bool:
    """Third-party rows are kept only when about orthopaedics / surgery (title, category, then the card's teaser). Pure."""
    return (classify_specialty(title) == "Musculoskeletal & Trauma"
            or bool(_RELEVANT_RE.search(f"{title} {category}")) or bool(_RELEVANT_RE.search(teaser or "")))


def parse_future_congress(html: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """'2027 - 14th - 17th September, ACC Liverpool' lines of the Future Congresses page: the next one with a full date. Pure."""
    today = today or date.today()
    lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|nav|footer|header)\b.*?</\1>", " ", html or ""))
    text = "\n".join(lines)
    for m in re.finditer(rf"(\d{{4}})\s*-\s*(\d{{1,2}})(?:st|nd|rd|th)?\s*-\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON_RE})\s*,?\s*\n?\s*([^\n]*)", text, re.I):
        y, d1, d2, mon, venue = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5).strip()
        a, b = _iso(y, _MONTHS[mon[:3].lower()], d1), _iso(y, _MONTHS[mon[:3].lower()], d2)
        if a and b and b >= a and b >= today.isoformat():
            return {"start": a, "end": b, "venue": re.sub(r"\s*-\s*TBC$", "", venue).strip(" ,") or None}
    return None


class BoaExtractor(EmsCalendarExtractor):
    ROOT = "https://www.boa.ac.uk"
    CALENDAR_PATH = "/learning-and-events/ems-event-calendar.html"
    LISTING_URL = ROOT + CALENDAR_PATH
    SOCIETY = "British Orthopaedic Association"
    DEFAULT_SPECIALTY = "Orthopaedics"
    DEFAULT_CURRENCY = "GBP"

    _dropped_off_topic = 0

    def skip_card(self, card: Dict[str, Any]) -> bool:
        if super().skip_card(card):
            return True
        if is_third_party(card) and not is_relevant(card.get("title") or "", card.get("type") or "", card.get("teaser") or ""):
            self._dropped_off_topic += 1
            logger.info(f"BOA: dropped off-topic third-party row: {card.get('title')!r} ({card.get('type')})")
            return True
        return False

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        self._dropped_off_topic = 0
        shells = super().list_shells_override()
        logger.info(f"BOA: {self._dropped_off_topic} third-party rows dropped as off-topic")
        return shells

    def extra_shells(self) -> List[Dict[str, Any]]:
        html = fetch_html(_FUTURE_CONGRESS_URL, browser=getattr(self, "browser", None))
        fc = parse_future_congress(html or "")
        if not fc:
            return []
        year = fc["start"][:4]
        url = f"{_FUTURE_CONGRESS_URL}#annual-congress-{year}"
        return [{"title": f"BOA Annual Congress {year}", "booking_url": url, "source_url": url, "start_date": fc["start"],
                 "end_date": fc["end"], "start_time": None, "venue_raw": fc["venue"], "category": "Annual Congress",
                 "badges": [], "cpd_points_listing": None, "teaser": "", "has_page": False}]

    def synthetic_detail(self, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        venue = shell.get("venue_raw")
        out: Dict[str, Any] = {"society": self.SOCIETY, "event_type": "conference", "specialty": self.DEFAULT_SPECIALTY,
                               "start_date": shell["start_date"], "end_date": shell["end_date"], "pricing_tiers": [],
                               "description": (f"The {shell['title']}, the British Orthopaedic Association's flagship annual meeting"
                                               f"{', at ' + venue if venue else ''}. Programme and registration details have not been published yet.")}
        if venue:
            out["venue_name"] = venue
            m = re.search(r"\b(Liverpool|London|Aberdeen|Manchester|Birmingham|Edinburgh|Glasgow|Cardiff|Belfast|Harrogate)\b", venue)
            if m:
                out["city"], out["region"] = m.group(1), _UK_PLACES.get(m.group(1).lower(), "United Kingdom")
            out["event_format"] = "in_person"
        return out

    def specialty_for(self, title: str, description: Optional[str], llm_call: Callable[[str], Optional[str]]) -> Optional[str]:
        spec = classify_specialty(title)
        if spec == "Musculoskeletal & Trauma":
            return self.DEFAULT_SPECIALTY
        if spec and spec not in _CLINICAL_NOISE:
            return spec
        if _RELEVANT_RE.search(title):
            return self.DEFAULT_SPECIALTY
        # a third-party listing with no orthopaedic cue in the title (cardiology forum, gut-health expo): ask once, keep default as the backstop
        if llm_call:
            try:
                resp = (llm_call("Name the single medical specialty (1-3 words, e.g. Cardiology) this event is for. "
                                 f"Reply with only the specialty or NONE.\nTitle: {title}\nText: {(description or '')[:800]}") or "").strip().strip(".\"'")
                if resp and resp.upper() != "NONE" and len(resp) <= 40:
                    return resp
            except Exception:  # noqa: BLE001
                pass
        return self.DEFAULT_SPECIALTY
