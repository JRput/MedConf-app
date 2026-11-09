"""Orthopaedic Research Society (ORS): flagship Annual Meeting plus the society's other meetings (ors.org, WordPress/Avada).

`/events/` embeds a Tockify calendar (client-side JS, third-party widget) of opportunities and awards. The society's real events
have static pages instead, all listed in the site menu under "Events" (before "Previous Meetings"): the Annual Meeting, the
ORS-ISTS Tendon Summit, the Musculoskeletal Biology Workshop, the PSRS spine symposium ... So the menu is the listing: every
candidate page is fetched and kept only when it parses to a dated event (title, "Month D - D, YYYY", venue/city lines) that has not
finished; programmes without a date (Young Investigator Initiative, Ambassador events) fall out and are logged. Annual meetings
announced only on `/futureannualmeetings/` (save-the-date: city, venue, dates) become extra shells when they start within 18 months
and have no page of their own yet.

Fees: the Annual Meeting links "Rates and Information" (`/register2027/`): a member / non-member x early / regular USD grid with an
early-bird end date. A registration page is used only when its OWN heading names the event year, because the workshop's
"Registration" link still points at the 2025 rate page. Everything is deterministic; no LLM.
"""
import html as html_lib
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines

ROOT = "https://www.ors.org"
EVENTS_URL = ROOT + "/events/"
FUTURE_URL = ROOT + "/futureannualmeetings/"
SOCIETY = "ORS"
SPECIALTY = "Orthopaedics"
HORIZON_DAYS = 540

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MON = "|".join(_MONTHS)
_DATE_RE = re.compile(rf"(?i)^({_MON})\s+(\d{{1,2}})\s*[-–—]\s*(?:({_MON})\s+)?(\d{{1,2}}),?\s+(20\d\d)$")
_STATES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|"
           "Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|"
           "New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
           "South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming")
_STATE_RE = re.compile(rf"^(?:{_STATES}|[A-Z]{{2}}|D\.?C\.?)$")
_VENUE_RE = re.compile(r"(?i)\b(center|centre|hotel|resort|lodge|hyatt|marriott|hilton|convention|hall|university|spa|inn|moscone|campus)\b")
_NOT_EVENT_LINK_RE = re.compile(r"(?i)ambassador|future annual|orthopaedic events|young investigator|clinician scholar|^events$|previous")


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def menu_event_links(html: str) -> List[Dict[str, str]]:
    """Anchors of the site menu between 'Events' and 'Previous Meetings' that can be event pages (hrefs on ors.org). Pure."""
    anchors = [(m.group(1), _clean(m.group(2))) for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html or "")]
    try:
        end = next(i for i, (_, t) in enumerate(anchors) if t == "Previous Meetings")
        start = max(i for i, (_, t) in enumerate(anchors[:end]) if t == "Events")
    except (StopIteration, ValueError):
        return []
    out, seen = [], set()
    for href, text in anchors[start + 1:end]:
        if not text or _NOT_EVENT_LINK_RE.search(text) or not href.startswith(ROOT) or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "text": text})
    return out


def content_lines(html: str) -> List[str]:
    """Text lines of the page body: after the menu's 'ORS Cookie Policy', before the footer's 'Volunteer Opportunities'. Pure."""
    lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", " ", html or ""))
    try:
        i = max(k for k, l in enumerate(lines) if l == "ORS Cookie Policy")
    except ValueError:
        return lines
    j = next((k for k, l in enumerate(lines) if k > i and l == "Volunteer Opportunities"), len(lines))
    return lines[i + 1:j]


def page_heading(lines: List[str]) -> Optional[str]:
    """The page's own title: the line before the '<title> aeadmin 2026-10-30T..' post-meta line. Pure."""
    for k, l in enumerate(lines):
        if re.search(r"\b(?:aeadmin|wp-support)\s+20\d\d-\d\d-\d\dT", l):
            return re.sub(r"\s+(?:aeadmin|wp-support)\s+20\d\d-.*$", "", l).strip()
    return None


def _place_line(l: str) -> bool:
    if len(l) > 90 or _DATE_RE.match(l):
        return False
    parts = [p.strip() for p in l.split(",")]
    return (len(parts) >= 2 and bool(_STATE_RE.match(parts[-1]))) or bool(_VENUE_RE.search(l))


def parse_event_block(lines: List[str]) -> Optional[Dict[str, Any]]:
    """First 'Month D - D, YYYY' line and the venue / 'City, State' lines within two lines of it. Pure."""
    for i, l in enumerate(lines):
        m = _DATE_RE.match(l)
        if not m:
            continue
        y = int(m.group(5))
        m1 = _MONTHS[m.group(1).lower()]
        m2 = _MONTHS[m.group(3).lower()] if m.group(3) else m1
        start, end = _iso(y, m1, int(m.group(2))), _iso(y, m2, int(m.group(4)))
        if not start or not end:
            continue
        near = [lines[k] for k in (i - 2, i - 1, i + 1, i + 2) if 0 <= k < len(lines) and _place_line(lines[k])]
        venue = city = state = None
        for p in near:
            parts = [x.strip() for x in p.split(",")]
            if len(parts) >= 3 and _STATE_RE.match(parts[-1]):                 # 'Hyatt Regency Boston, Boston, MA'
                venue, city, state = ", ".join(parts[:-2]), parts[-2], parts[-1]
            elif len(parts) == 2 and _STATE_RE.match(parts[-1]):               # 'San Francisco, California'
                city, state = city or parts[0], state or parts[1]
            elif _VENUE_RE.search(p) and not venue:                            # 'Moscone West Convention Center'
                venue = p
        return {"start": start, "end": end, "venue": venue, "city": city, "state": state}
    return None


def parse_future_meetings(html: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """'ORS 2028 Annual Meeting' blocks of /futureannualmeetings/ (title, 'City, State', venue, dates) starting within the horizon. Pure."""
    today = today or date.today()
    lines = content_lines(html)
    out = []
    for i, l in enumerate(lines):
        tm = re.match(r"^ORS (20\d\d) Annual Meeting$", l)
        if not tm:
            continue
        blk = parse_event_block(lines[i: i + 6])
        if not blk or blk["end"] < today.isoformat() or date.fromisoformat(blk["start"]) > today + timedelta(days=HORIZON_DAYS):
            continue
        out.append({"title": l, **blk})
    return out


def parse_fee_grid(lines: List[str], year: int) -> List[Dict[str, Any]]:
    """ORS registration grid -> USD tiers. Rows are 'Category', 'Description', '$early', '$regular' (Non-Member has no description).
    The early-bird end date comes from 'Early Bird Registration Rates End <Month D, YYYY>'. Pure."""
    text = " ".join(lines)
    em = re.search(rf"(?i)Early Bird Registration Rates End\s+({_MON})\s+(\d{{1,2}}),\s*(20\d\d)", text)
    deadline = _iso(int(em.group(3)), _MONTHS[em.group(1).lower()], int(em.group(2))) if em else None
    start = next((i for i, l in enumerate(lines) if re.match(r"(?i)^ORS Member Registration Type$", l)), None)
    if start is None:
        return []
    stop = next((i for i, l in enumerate(lines) if i > start and re.match(r"(?i)^(Renew Your Membership|ORS Membership Rates|Add-On)", l)), len(lines))
    section = "ORS member"
    tiers: List[Dict[str, Any]] = []
    price = re.compile(r"^\$\s*(\d[\d,]*(?:\.\d\d)?)$")
    i = start + 1
    while i < stop:
        l = lines[i]
        if re.match(r"(?i)^Non-Member Registration Type$", l):
            section = "Non-member"
        if price.match(l) and i + 1 < stop and price.match(lines[i + 1]):
            cat = lines[i - 1]
            if i >= 2 and (len(cat) > 25 or "," in cat) and not re.match(r"(?i)^(Early Registration Rate|Registration Rate)$", lines[i - 2]):
                cat = lines[i - 2]
            e, r = float(price.match(l).group(1).replace(",", "")), float(price.match(lines[i + 1]).group(1).replace(",", ""))
            head = section if cat.lower().replace("-", " ") == section.lower().replace("-", " ") else f"{section} · {cat}"
            tiers.append({"tier_label": f"{head} · Early registration", "price_gbp": e, "currency": "USD",
                          "is_early_bird": True, "early_bird_deadline": deadline})
            tiers.append({"tier_label": f"{head} · Regular registration", "price_gbp": r, "currency": "USD",
                          "is_early_bird": False, "early_bird_deadline": None})
            i += 2
            continue
        i += 1
    return tiers


def parse_abstract_lines(lines: List[str], today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """ORS pages state abstract timing as 'December 1, 2026: Abstract Submission Opens' / 'February 5, 2027: Abstract Deadline'
    (the shared classifier mistakes the 'Notifications Sent' date for the deadline here) or as 'General Call: Closed' /
    'Late Breaking: Open' status lines. Pure; None when the page says neither."""
    today = today or date.today()
    opens = deadline = None
    for l in lines:
        m = re.match(rf"(?i)^({_MON})\s+(\d{{1,2}}),\s*(20\d\d)\s*:\s*(.+)$", l)
        if not m:
            continue
        d = _iso(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        if re.search(r"(?i)abstract submission opens?", m.group(4)):
            opens = d
        elif re.search(r"(?i)abstract (?:submission )?deadline", m.group(4)):
            deadline = d
    if deadline:
        is_open = bool((opens is None or opens <= today.isoformat()) and deadline >= today.isoformat())
        return {"open": is_open, "deadline": deadline, "note": None}
    text = " ".join(lines)
    general = re.search(r"(?i)General Call\s*:\s*(Open|Closed)", text)
    late = re.search(r"(?i)Late[- ]Breaking\s*:\s*(Open|Closed)", text)
    if late and late.group(1).lower() == "open":
        return {"open": True, "deadline": None,
                "note": "General call closed; late-breaking abstracts open" if general and general.group(1).lower() == "closed" else "Late-breaking abstracts open"}
    if general and general.group(1).lower() == "open":
        return {"open": True, "deadline": None, "note": None}
    return None


def event_type_for(title: str) -> str:
    return "workshop" if re.search(r"(?i)\bworkshop\b", title) else "conference"


class OrsExtractor(BaseExtractor):

    def _fetch(self, url: str) -> Optional[str]:
        return fetch_html(url, browser=getattr(self, "browser", None))

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(EVENTS_URL)
        if not html:
            logger.warning("ORS: /events/ fetch failed")
            return None
        today = date.today()
        shells: List[Dict[str, Any]] = []
        dropped: List[str] = []
        for link in menu_event_links(html):
            page = self._fetch(link["url"])
            lines = content_lines(page or "")
            blk = parse_event_block(lines[:40]) if lines else None
            if not blk:
                dropped.append(f"{link['text']} (no dated event on the page)")
                continue
            if blk["end"] < today.isoformat():
                dropped.append(f"{link['text']} (finished {blk['end']})")
                continue
            title = link["text"]
            if not re.search(r"\bORS\b", title):
                title = "ORS " + title
            if not re.search(r"\b20\d\d\b", title):
                title = f"{title} {blk['start'][:4]}"
            shells.append(self._shell(title, link["url"], blk, page))
        have_years = {s["start_date"][:4] for s in shells if re.search(r"Annual Meeting", s["title"])}
        fut_html = self._fetch(FUTURE_URL)
        for f in parse_future_meetings(fut_html or "", today):
            if f["start"][:4] in have_years:
                continue
            shells.append(self._shell(f["title"], f"{FUTURE_URL}#annual-meeting-{f['start'][:4]}", f, None, save_the_date=True))
        for d in dropped:
            logger.info(f"ORS: dropped {d}")
        logger.info(f"ORS: {len(shells)} upcoming events ({len(dropped)} menu items dropped)")
        return shells

    @staticmethod
    def _shell(title: str, url: str, blk: Dict[str, Any], page_html: Optional[str], save_the_date: bool = False) -> Dict[str, Any]:
        place = ", ".join(x for x in (blk.get("venue"), blk.get("city"), blk.get("state")) if x)
        shell = {"title": title, "booking_url": url, "start_date": blk["start"], "end_date": blk["end"], "venue_raw": place or None,
                 "venue": blk.get("venue"), "city": blk.get("city"), "state": blk.get("state"), "save_the_date": save_the_date}
        if page_html:
            for m in re.finditer(r'(?is)<a\b[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', page_html):
                if re.fullmatch(r"(?i)rates and information|registration( rates)?", _clean(m.group(2))) and urlparse(m.group(1)).netloc.endswith("ors.org"):
                    shell["fee_url"] = m.group(1)
                    break
        return shell

    def _fees(self, shell: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = shell.get("fee_url")
        if not url:
            return []
        html = self._fetch(url)
        if not html:
            return []
        lines = content_lines(html)
        heading = page_heading(lines) or ""
        year = shell["start_date"][:4]
        years = set(re.findall(r"\b20\d\d\b", heading))
        if years != {year}:                    # the page's own heading must name this edition (workshop link still points at 2025)
            logger.info(f"ORS: fee page {url} not used for {shell['title']!r}: heading {heading!r} does not name only {year}")
            return []
        tiers = parse_fee_grid(lines, int(year))
        for t in tiers:
            t["evidence_url"], t["evidence_identity"] = url, "strong"
        return tiers

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": SOCIETY, "specialty": SPECIALTY, "event_type": event_type_for(shell["title"]),
                               "start_date": shell["start_date"], "end_date": shell.get("end_date"), "event_format": "in_person",
                               "pricing_tiers": []}
        if shell.get("venue"):
            out["venue_name"] = shell["venue"]
        if shell.get("city"):
            out["city"] = shell["city"]
            if shell.get("state"):
                out["region"] = "United States"
        if shell.get("save_the_date"):
            out["description"] = (f"{shell['title']} (save the date) at {shell['venue_raw']}." if shell.get("venue_raw")
                                  else f"{shell['title']} (save the date).")
            # The page also carries the NEXT meeting's abstract windows; a note here stops the pipeline's page-text classifier
            # from attaching them to this later edition.
            out["abstract_deadline_note"] = "Abstract dates not announced yet"
            return out

        url = shell["booking_url"]
        html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) or (page.content() if page is not None else "")
        lines = content_lines(html)
        meta = next((i for i, l in enumerate(lines) if re.search(r"\b(?:aeadmin|wp-support)\s+20\d\d-\d\d-\d\dT", l)), -1)
        for l in lines[meta + 1:]:
            if len(l) >= 80 and not _DATE_RE.match(l) and not re.match(r"(?i)^(additional details|this unique|registration|abstract)", l):
                out["description"] = l if len(l) <= 400 else l[:397] + "..."
                break
        ab = parse_abstract_lines(lines)
        if ab:
            out["abstract_open"], out["abstract_deadline"] = ab["open"], ab["deadline"]
            if ab["note"]:
                out["abstract_deadline_note"] = ab["note"]
        if not out.get("description") and meta >= 0 and meta + 2 < len(lines) and lines[meta + 1].endswith(":"):
            out["description"] = f"{lines[meta + 1]} {lines[meta + 2]}"[:400]
        out["pricing_tiers"] = self._fees(shell)
        return out
