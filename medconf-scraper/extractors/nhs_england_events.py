"""NHS England events portal (events.england.nhs.uk), a Sigma Technology ticketing site (Materialize CSS), server-rendered.

Listing: `/events?page=N` (about 20 cards a page, 4 pages when written, an empty page ends the walk). A card is
`<div class="card ... data-url="/<id>">` with the title, "DD Month YYYY" and " - <location>" ("Virtual (MS Teams)", "Location TBC", "London").
Detail `/<id>`: `<h1>`, `.mvp_date` ("17 November 2026 9:30am - 5:00pm GMT"), `.mvp_address`, a `.mvp_tickets` block with one
`.mvp_ticket` per ticket type (label, FREE / price chip, "Fully Booked" badge) and a `.mvp_body` description.

The portal also carries NHS-internal business: IT/system inductions, communications and HR courses, supplier open days, co-production
forums. MedConf is for clinicians' CPD, so a row is kept only when its title carries a clinical, education or clinical-leadership cue
and no admin cue (see `is_relevant`); every dropped title is logged. Unmatched titles default to DROPPED (conservative).
No LLM calls: description is the first real paragraph of the event body, specialty comes from the shared title classifier.
"""
import html as html_lib
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from .tribe_events import html_to_lines

ROOT = "https://www.events.england.nhs.uk"
LISTING_URL = ROOT + "/events"
SOCIETY = "NHS England"
MAX_PAGES = 12

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MON = "|".join(_MONTHS)
_DATE_RE = re.compile(rf"(?i)\b(\d{{1,2}})\s+({_MON})\s+(20\d\d)\b")
_CARD_SPLIT_RE = re.compile(r'data-url="(/\d+)"')

# Clinical / education / clinical-leadership cues. Only used together with the DROP list below.
_KEEP_RE = re.compile(
    r"(?i)clinical|clinician|patient|\bcare\b|carers?|nursing|\bnurses?\b|midwi|pharmac|physio|paramedic|(?-i:\bGPs?\b)|primary care|"
    r"\bGIRFT\b|hepatitis|renal|kidney|STEMI|cardi|oncolog|cancer|urolog|labour|obstetric|maternity|neonat|paediatric|children|"
    r"mental health|psychiatr|dementia|audiolog|audiometr|hearing|spinal|pain|diabet|stroke|respirat|vaccin|immunis|infection|sepsis|"
    r"urgent and emergency|(?-i:\bUEC\b)|(?-i:\bED\b)|emergency|surgery|surgical|anaesth|radiolog|pathology|dermatolog|ophthalm|\bENT\b|"
    r"learners?|educators?|education|training|revalidation|responsible officer|medical|doctors?|consultants?|workforce|"
    r"leadership|continuing care|outpatient|prevention|rehabilitation|palliative|end of life|safeguarding|"
    r"learning disabilit|autism|neurodivers|health inequalit|(?-i:\bAHPs?\b)|allied health|symposium|clinical network|network day")
_DROP_RE = re.compile(
    r"(?i)supplier|spend comparison|copilot|co-?pilot|agent-?a-?thon|\bCIPD\b|speechwriting|writing for your audience|communicat|"
    r"crisis comm|staff survey|NHS App\b|digital front door|digi-?bites|contract dispute|coaching champions|co-?production|"
    r"induction session|exhibitor|\bprocurement\b|\bfinance\b|\bpayroll\b|(?-i:\bIT\b)|cyber|data protection|information governance|"
    r"open event|violence prevention|clock club|working with partners|media training|\bpress\b")


def is_relevant(title: str) -> bool:
    """CPD-relevant for clinicians: a clinical/education/leadership cue and no administrative cue. Pure."""
    t = title or ""
    return bool(_KEEP_RE.search(t)) and not _DROP_RE.search(t)


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_listing(html: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """One listing page -> raw card dicts {id, title, start_date, location}. Pure."""
    today = today or date.today()
    out: List[Dict[str, Any]] = []
    parts = _CARD_SPLIT_RE.split(html or "")
    # parts = [prefix, id1, chunk1, id2, chunk2, ...]
    for i in range(1, len(parts) - 1, 2):
        cid, chunk = parts[i], parts[i + 1]
        chunk = re.split(r'(?is)<ul class="pagination"|<div class="ch-cookie-consent', chunk)[0]
        chunk = re.sub(r'^[^<]*?>', '', chunk, count=1)           # the rest of the opening data-url tag
        lines = html_to_lines(chunk)
        line = next((l for l in lines if _DATE_RE.search(l)), None)
        if not line:
            continue
        dm = list(_DATE_RE.finditer(line))[-1]
        title = html_lib.unescape(line[:dm.start()]).strip()
        if not title:
            continue
        start = _iso(int(dm.group(3)), _MONTHS[dm.group(2).lower()], int(dm.group(1)))
        loc = None
        idx = lines.index(line)
        for l in lines[idx + 1: idx + 3]:
            if l.startswith("-"):
                loc = l.lstrip("- ").strip()
                break
        if not start or start < today.isoformat():
            continue
        out.append({"id": cid, "title": re.sub(r"\s+", " ", title), "start_date": start, "location": loc})
    return out


def split_address(raw: str) -> Dict[str, Any]:
    """'Park Plaza London Waterloo, 6 Hercules Road, London, SE1 7DP, United Kingdom' -> venue/city/region. Pure."""
    raw = re.sub(r"\s+,", ",", re.sub(r"\s+", " ", raw or "")).strip(" ,")
    raw = re.sub(r",?\s*(?:United Kingdom|UK|England)\s*$", "", raw)
    raw = re.sub(r",?\s*\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b\s*$", "", raw).strip(" ,")
    parts = [p.strip() for p in re.split(r",+", raw) if p.strip()]
    if not parts:
        return {}
    regions = ("East of England", "North East", "North West", "South East", "South West", "West Midlands", "East Midlands",
               "Yorkshire and the Humber")
    out: Dict[str, Any] = {"event_format": "in_person"}
    region = None
    if len(parts) > 1 and parts[-1] in regions:
        region = parts.pop()
    city = parts[-1] if len(parts) > 1 else None
    if city is None and region is None:
        city = parts[0]
    venue = ", ".join(parts[:-1]) if len(parts) > 1 else (None if city else parts[0])
    if len(parts) == 1 and region is None:           # a bare place name such as "London" / "Canary Wharf" / "Manchester"
        venue = None
    if city:
        out["city"] = city[:80]
    out["region"] = region or ("London" if (city or "").lower() == "london" else "England")
    if venue:
        out["venue_name"] = venue[:200]
    return out


_TITLE_SPECIALTY = [(r"renal|kidney", "Nephrology"), (r"labour|maternity|maternal|obstetric|neonat", "Women's Health"),
                    (r"physio|spinal|musculoskeletal|\bMSK\b", "Musculoskeletal & Trauma"), (r"hepatitis|vaccin", "Infectious Disease"),
                    (r"audiolog|audiometr|hearing", "ENT"), (r"leadership|responsible officer|revalidation|job planning", "Leadership & Management")]


def _title_specialty(title: str) -> Optional[str]:
    """Labels the shared classifier lacks cues for; title only (page text mis-tags: a renal day read as Cardiology). Pure."""
    for rx, label in _TITLE_SPECIALTY:
        if re.search(rf"(?i){rx}", title or ""):
            return label
    return None


def _format_from_cues(dates: List[str], title: str, body: str, has_place: bool) -> Optional[str]:
    """Format when the location block gives no venue and no Teams/webinar cue: a real address means in_person; 'Location TBC' with a
    learning-programme cue ('animation-based', e-learning, self-paced, modules) or a date span over two weeks is an online
    programme; otherwise unknown (None) rather than a guess. Pure."""
    if has_place:
        return "in_person"
    if re.search(r"(?i)animation-based|e-?learning|self-paced|online module|learning programme", f"{title} {body[:800]}"):
        return "online"
    if len(dates) > 1 and dates[0] and dates[-1]:
        try:
            if (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days > 14:
                return "online"
        except ValueError:
            pass
    return None


def event_type_for(title: str) -> str:
    t = title.lower()
    if re.search(r"conference|symposium|network day|summit|annual|forum|congress", t):
        return "conference"
    if re.search(r"training|course|programme|masterclass", t):
        return "course"
    return "workshop"


def parse_tickets(html: str, title: str = "") -> List[Dict[str, Any]]:
    """`.mvp_ticket` blocks -> GBP tiers (FREE -> one 0.00 tier), plus nothing for ticket types without a price chip. Pure."""
    tiers: List[Dict[str, Any]] = []
    seen = set()
    for m in re.finditer(r'(?is)<div class="js-saleable-item mvp_ticket".*?(?=<div class="js-saleable-item mvp_ticket"|<div class="col s12"><a class="btn-large|Questions about this event|$)', html or ""):
        blk = m.group(0)
        hm = re.search(r'(?is)<div class="h3_dummy[^"]*">(.*?)</div>', blk)
        label = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r'(?is)<span class="new badge.*?</span>', " ", hm.group(1) if hm else "")))).strip()
        chip = re.search(r'(?is)class="chip price[^"]*">(.*?)</span>', blk)
        chip_t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", chip.group(1))).strip() if chip else ""
        if re.fullmatch(r"(?i)free", chip_t):
            price = 0.0
        else:
            pm = re.search(r"£\s*(\d[\d,]*(?:\.\d{1,2})?)", chip_t)
            if not pm:
                continue
            price = float(pm.group(1).replace(",", ""))
        echoes_title = bool(title) and (label.lower() in title.lower() or title.lower() in label.lower())
        label = "Registration" if (not label or echoes_title or re.fullmatch(r"(?i)register here|book now|reserve|tickets?", label)) else label
        if (label, price) in seen:
            continue
        seen.add((label, price))
        tiers.append({"tier_label": label[:120], "price_gbp": price, "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
    return tiers


def _is_sold_out(html: str) -> bool:
    blocks = re.findall(r'(?is)<div class="js-saleable-item mvp_ticket".*?</form>', html or "")
    return bool(blocks) and all(re.search(r"(?i)fully booked|sold out", b) for b in blocks)


class NhsEnglandEventsExtractor(BaseExtractor):

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells: List[Dict[str, Any]] = []
        seen = set()
        dropped: List[str] = []
        total = 0
        for page_no in range(1, MAX_PAGES + 1):
            url = LISTING_URL if page_no == 1 else f"{LISTING_URL}?page={page_no}"
            html = fetch_html(url, browser=getattr(self, "browser", None))
            if not html:
                if page_no == 1:
                    logger.warning("NHS England events: listing fetch failed")
                    return None
                break
            cards = parse_listing(html)
            new = [c for c in cards if c["id"] not in seen]
            if not new:
                break
            for c in new:
                seen.add(c["id"])
                total += 1
                if not is_relevant(c["title"]):
                    dropped.append(c["title"])
                    continue
                shells.append({"title": c["title"], "booking_url": ROOT + c["id"], "start_date": c["start_date"],
                               "venue_raw": None if (c["location"] or "").lower().startswith("location tbc") else c["location"]})
            time.sleep(0.5)
        for t in dropped:
            logger.info(f"NHS England events: dropped as not clinician-CPD: {t!r}")
        logger.info(f"NHS England events: {len(shells)} kept of {total} upcoming listed ({len(dropped)} dropped)")
        return shells

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) if url else None
        if not html:
            html = page.content() if page is not None else ""
        title = shell.get("title") or ""
        out: Dict[str, Any] = {"society": SOCIETY, "event_type": event_type_for(title), "pricing_tiers": []}

        h1 = re.search(r"(?is)<h1>(.*?)</h1>", html)
        if h1:
            name = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", h1.group(1)))).strip()
            if name:
                out["conference_name"] = name

        dm = re.search(r'(?is)<div class="mvp_date">(.*?)</div>', html)
        date_text = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", dm.group(1)))).strip() if dm else ""
        found = [_iso(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))) for m in _DATE_RE.finditer(date_text)]
        found = [d for d in found if d]
        if found:
            out["start_date"] = found[0]
            if len(found) > 1 and found[-1] != found[0]:
                out["end_date"] = found[-1]
        tm = re.search(r"(?i)\b(\d{1,2}):(\d{2})\s*([ap])m\b", date_text)
        if tm:
            hh = int(tm.group(1)) % 12 + (12 if tm.group(3).lower() == "p" else 0)
            out["start_time"] = f"{hh:02d}:{tm.group(2)}"

        am = re.search(r'(?is)<div class="mvp_address">(.*?)</div>', html)
        addr = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", am.group(1)))).strip() if am else ""
        addr = re.sub(r"\s+,", ",", addr)
        body_m = re.search(r'(?is)class="col s12 mvp_body">(.*?)Questions about this event', html)
        body_lines = html_to_lines(body_m.group(1)) if body_m else []
        body_text = " ".join(body_lines)
        online_cue = re.search(r"(?i)\b(virtual|online|teams|webinar|zoom|town hall)\b", f"{addr} {shell.get('venue_raw') or ''} {title}")
        tbc = not addr or bool(re.match(r"(?i)^location tbc", addr))
        if addr and not tbc and not online_cue:
            out.update(split_address(addr))
        elif online_cue or (tbc and re.search(r"(?i)\bwebinar\b|\bonline\b|\bvirtual\b|via (?:microsoft )?teams", body_text[:700])):
            out["event_format"] = "online"
        elif shell.get("venue_raw"):
            out.update(split_address(shell["venue_raw"]))

        if not out.get("event_format"):
            out["event_format"] = _format_from_cues(found, title, body_text, bool(out.get("venue_name") or out.get("city")))
            if out["event_format"] is None:
                out.pop("event_format")
        out["pricing_tiers"] = parse_tickets(html, title)
        if _is_sold_out(html):
            out["is_sold_out"] = True

        desc = next((l for l in body_lines if len(l) >= 60 and re.match(r"[A-Za-z\"'(]", l)
                     and not re.match(r"(?i)^(name|email|telephone|event details|location|date|time)\b", l)
                     and not re.search(r"(?i)sponsor|financial support|editorial input", l)
                     and l.lower() not in title.lower() and title.lower() not in l.lower()), None)
        if desc:
            if len(desc) > 400:
                cut = desc[:400]
                idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
                desc = cut[:idx + 1] if idx >= 150 else cut.rstrip() + "..."
            out["description"] = desc
        spec = classify_specialty(title)
        if spec == "General Practice" and not re.search(r"(?i)\bGPs?\b|general practice|primary care", title):
            spec = None                                  # the classifier's 'annual conference' catch-all (HQ LESSONS: GP-heavy sources)
        out["specialty"] = spec or _title_specialty(title) or "Multi-specialty"
        cm = re.search(r"(\d+(?:\.\d+)?)\s*CPD\s*(?:points?|credits?|hours?)", body_text, re.I)
        if cm:
            out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
        return out
