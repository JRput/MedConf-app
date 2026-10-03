# extractors/advance_he.py
"""
Advance HE (UK higher-education leadership / teaching / governance body) —
event extractor. Source 53.

Platform: WordPress block theme, server-rendered, no bot protection.

Listing  https://advance-he.ac.uk/events/?query-10-page=N   (6 items/page,
         ~20 pages, ~115 events, ascending by start date). Each <li> carries:
             h2.event-teaser__event-title   -> title
             span.event-teaser__date[data-date]  -> start epoch (UTC)
             a.event-teaser__event-link[href]    -> detail URL
         The last page is the first one whose <li> list is empty / short.

Detail   Sparse "event-details" block, identical on every page:
             "Event type"   -> Conference / Aurora / Member Benefit Event ...
             "Event times"  -> one `.event-details__schedule-datetime` row per
                               session ("Wed 2 Dec 2026 – Wed 2 Dec 2026"),
                               plus data-session JSON {start,end,loc} (epoch)
                               on most pages (absent on some programmes)
             "Event prices" -> <table><tr><td>product</td><td>ticket</td><td>£N</td>
             a.event-details__booking-link -> my.advance-he.ac.uk booking portal
         Rich pages (conferences) also carry intro paragraphs; most pages
         have no description and no venue at all, so those stay None.

Many events are not medical (governance, surveys, leadership). They are kept:
the provider is on the masterlist for healthcare educators. Specialty is
limited to "Medical Education" / "Leadership & Management" (or a clinical
one only when the shared classifier finds it in the title).
"""

import re
import json
import html as _htmlmod
import time
from datetime import date, datetime, timezone
from typing import Dict, Any, Optional, Callable, List
from zoneinfo import ZoneInfo

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger


LISTING_URL = "https://advance-he.ac.uk/events/"
MAX_PAGES = 30           # hard ceiling; observed 20 pages
REQUEST_DELAY_S = 1.1    # <= ~1 req/s
_LONDON = ZoneInfo("Europe/London")

_LI_RE = re.compile(r'<li class="wp-block-post[^"]*events[^"]*">(.*?)</li>', re.DOTALL)
_TITLE_RE = re.compile(r'event-teaser__event-title">\s*(.*?)\s*</h2>', re.DOTALL)
_DATE_RE = re.compile(r'data-date="(\d+)"')
_HREF_RE = re.compile(r'href="([^"]+)"[^>]*class="event-teaser__event-link"')

_DT_ROW_RE = re.compile(r'class="event-details__schedule-datetime">(.*?)</p>', re.DOTALL)
_SESSION_RE = re.compile(r'data-session="([^"]+)"')
_TYPE_RE = re.compile(r'Event type</h2>\s*<p>(.*?)</p>', re.DOTALL)
_PRICE_TABLE_RE = re.compile(r'Event prices</h2>.*?<table>(.*?)</table>', re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_TXT_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(20\d{2})")

_ONLINE_RE = re.compile(r"\b(webinar|online|virtual|zoom|microsoft teams)\b", re.I)
_SOLD_OUT_RE = re.compile(r"sold out|fully booked|event (?:is )?full|waiting list", re.I)

_LEADERSHIP_KW = (
    "leadership", "leading", "leader", "management", "governance", "governor", "governing",
    "board", "aurora", "diversifying", "women", "inclusive", "inclusion", "equality",
    "diversity", "surveys", "clerks", "secretaries", "mentor", "athena",
    "financial", "audit", "strategic",
)


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _htmlmod.unescape(s)).strip()


def _london(epoch: int) -> datetime:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).astimezone(_LONDON)


def _parse_txt_date(txt: str) -> Optional[str]:
    m = _DATE_TXT_RE.search(txt or "")
    if not m:
        return None
    mon = _MONTHS.get(m.group(2).lower())
    if not mon:
        return None
    try:
        return date(int(m.group(3)), mon, int(m.group(1))).isoformat()
    except ValueError:
        return None


class AdvanceHeExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — server-rendered paginated WordPress query loop
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen: set = set()
        pages_ok = 0

        for n in range(1, MAX_PAGES + 1):
            url = LISTING_URL if n == 1 else f"{LISTING_URL}?query-10-page={n}"
            html = None
            for attempt in range(3):
                html = fetch_html(url, browser=browser)
                if html and "wp-block-post" in html:
                    break
                time.sleep(2 * (attempt + 1))
            if not html:
                logger.warning(f"AdvanceHE: listing page {n} unavailable after 3 tries")
                break
            lis = _LI_RE.findall(html)
            if not lis:
                break  # ran past the last page
            pages_ok += 1
            new_on_page = 0
            for li in lis:
                t = _TITLE_RE.search(li)
                h = _HREF_RE.search(li)
                if not t or not h:
                    continue
                href = _htmlmod.unescape(h.group(1))
                if href in seen:
                    continue
                seen.add(href)
                new_on_page += 1
                start_iso = None
                d = _DATE_RE.search(li)
                if d:
                    start_iso = _london(int(d.group(1))).date().isoformat()
                # Past events (start already gone) are not upcoming. Programmes
                # that started earlier but run on are rare on this site.
                if start_iso and date.fromisoformat(start_iso) < today:
                    continue
                shells.append({
                    "title": _clean(t.group(1)),
                    "booking_url": href,
                    "start_date": start_iso,
                    "start_time": None,
                    "is_sold_out": False,
                    "page_index": n,
                })
            if new_on_page == 0:
                break  # page repeated -> past the end
            time.sleep(REQUEST_DELAY_S)

        if not shells:
            logger.warning("AdvanceHE listing override found 0 shells; falling back to DOM walker")
            return None
        logger.info(f"AdvanceHE: {len(shells)} upcoming shells over {pages_ok} listing pages")
        return shells

    # ------------------------------------------------------------------ #
    # Detail
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        url = shell.get("booking_url") or ""
        try:
            html = page.content() or ""
        except Exception:
            html = ""
        if "event-details" not in html:
            html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) or html

        h1 = _H1_RE.search(html)
        title = _clean(h1.group(1)) if h1 else ""
        result["conference_name"] = title or shell.get("title")

        etype_m = _TYPE_RE.search(html)
        adv_type = _clean(etype_m.group(1)) if etype_m else ""

        # ---- dates / sessions (deterministic) ----
        rows = [_clean(r) for r in _DT_ROW_RE.findall(html)]
        epochs = []
        for raw in _SESSION_RE.findall(html):
            try:
                j = json.loads(_htmlmod.unescape(raw))
                epochs.append((int(j["start"]), int(j.get("end") or j["start"]), j.get("loc") or ""))
            except Exception:
                continue

        spans = []  # (start_iso, end_iso)
        for r in rows:
            found = _DATE_TXT_RE.findall(r)
            if not found:
                continue
            s_iso = _parse_txt_date(r)
            rest = r.split("–", 1)[1] if "–" in r else (r.split("-", 1)[1] if " - " in r else "")
            e_iso = _parse_txt_date(rest) or s_iso
            if s_iso:
                spans.append((s_iso, e_iso))

        today = date.today().isoformat()
        if spans:
            spans = [sp for sp in spans if (sp[1] or sp[0]) >= today]
        if not spans:
            return result  # past or undated — leave dates null

        spans.sort()
        result["start_date"] = spans[0][0]
        result["end_date"] = max(sp[1] for sp in spans)
        if len(spans) >= 2:
            result["sessions"] = [{
                "start_date": s, "end_date": e if e != s else None, "start_time": None,
                "duration_text": None, "availability_status": "unknown",
                "spots_left": None, "booking_url": None, "notes": None,
            } for s, e in spans]

        # start time from the first data-session (skip pure-midnight = date only)
        venue_loc = ""
        if epochs:
            epochs.sort()
            first = _london(epochs[0][0])
            if first.date().isoformat() == result["start_date"] and (first.hour or first.minute):
                result["start_time"] = first.strftime("%H:%M")
            venue_loc = next((l for _, _, l in epochs if l), "")

        # ---- text blobs ----
        body_text = self._main_text(html)
        result["event_type"] = self._event_type(adv_type, result["conference_name"], len(spans))

        mm = re.search(r"<main.*?</main>", html, re.DOTALL)
        main_html = re.split(r"Related events", mm.group(0))[0] if mm else ""
        result.update(self._soft_fields(result["conference_name"], main_html, llm_call))
        # ---- format / venue ----
        loc = _clean(venue_loc)
        fmt = None
        probe = f"{result['conference_name']} {loc} {self._subtitle(body_text)}"
        if re.search(r"hybrid", probe, re.I):
            fmt = "hybrid"
        elif _ONLINE_RE.search(probe) or re.search(
                r"\b(virtual|online) (programme|course|event|workshop|conference|session)s?\b",
                (result.get("description") or ""), re.I):
            fmt = "online"
        elif loc:
            fmt = "in_person"
        if fmt:
            result["event_format"] = fmt
        if loc and fmt == "in_person":
            result["venue_name"] = loc

        # ---- pricing ----
        result["pricing_tiers"] = self._pricing(html)

        # ---- sold out ----
        result["is_sold_out"] = bool(_SOLD_OUT_RE.search(body_text))

        # ---- CPD (only if the page states it) ----
        cm = re.search(r"(\d+(?:\.\d+)?)\s*CPD\s*(?:hours|points|credits)", body_text, re.I)
        if cm:
            result["cpd_points"] = float(cm.group(1))
            result["cpd_accredited"] = True

        return result

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _main_text(html: str) -> str:
        m = re.search(r"<main.*?</main>", html, re.DOTALL)
        t = m.group(0) if m else html
        t = re.sub(r"<(script|style|nav)[^>]*>.*?</\1>", " ", t, flags=re.DOTALL)
        t = re.sub(r"</(p|h\d|li|div|tr)>", "\n", t)
        t = re.sub(r"<[^>]+>", " ", t)
        t = _htmlmod.unescape(t)
        t = re.sub(r"[ \t\xa0]+", " ", t)
        t = re.split(r"\n\s*Related events", t)[0]
        return re.sub(r"\n\s*\n+", "\n", t).strip()

    @staticmethod
    def _subtitle(body_text: str) -> str:
        m = re.search(r"\d{1,2} \w+ 20\d{2},\s*([^\n]{0,40})", body_text)
        return m.group(1) if m else ""

    @staticmethod
    def _event_type(adv_type: str, title: str, n_sessions: int) -> str:
        t = f"{adv_type} {title}".lower()
        if re.search(r"conference|symposium|forum|summit|network event|awards", t):
            return "conference"
        if re.search(r"webinar|workshop|roadshow|panel|launch event|reviewer training|network", t):
            return "workshop"
        if re.search(r"programme|program|course|aurora|fellowship|training|cohort|leadership|"
                     r"top management|diversifying", t):
            return "course"
        return "conference"

    @staticmethod
    def _pricing(html: str) -> List[Dict[str, Any]]:
        m = _PRICE_TABLE_RE.search(html)
        if not m:
            return []
        rows = []
        for tr in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.DOTALL):
            cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)]
            if len(cells) < 2:
                continue
            pm = re.search(r"[£]\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", cells[-1])
            if not pm:
                continue
            rows.append((cells[0] if len(cells) >= 3 else "", cells[-2] if len(cells) >= 3 else cells[0],
                         float(pm.group(1).replace(",", ""))))
        if not rows:
            return []
        tiers, seen = [], set()
        for product, cat, price in rows:
            early = bool(re.search(r"early[\s-]*bird|\bEB\b", cat + " " + product, re.I))
            cat_clean = re.sub(r"\(?\s*early[\s-]*bird\s*\)?", "", cat, flags=re.I).strip(" -–")
            cat_clean = re.sub(r"\bticket\b", "", cat_clean, flags=re.I).strip(" -–") or cat
            cat_clean = re.sub(r"\s+", " ", cat_clean)
            if re.match(r"non[\s-]*member", cat_clean, re.I):
                cat_clean = "Non-Member"
            elif re.match(r"member", cat_clean, re.I) and len(cat_clean) <= 8:
                cat_clean = "Member"
            parts = ["Registration", cat_clean] + (["Early Bird"] if early else [])
            label = " · ".join(parts)
            if label in seen:
                # Same category sold under several products (e.g. per-date or
                # per-cohort rows): disambiguate with the product name.
                label = " · ".join(["Registration", product or cat_clean, cat_clean]
                                   + (["Early Bird"] if early else []))
                if label in seen:
                    continue
            seen.add(label)
            tiers.append({
                "tier_label": label, "price_gbp": price, "currency": "GBP",
                "is_early_bird": early, "early_bird_deadline": None,
            })
        return tiers

    def _soft_fields(
        self, title: str, main_html: str, llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        # Real prose = lines >= 80 chars outside the details/price block.
        sm = re.search(r"Event summary</h2>(.*?)</div>", main_html, re.DOTALL)
        summary = _clean(sm.group(1)) if sm else ""
        prose = ([summary] if len(summary) >= 30 else []) + [p for p in (_clean(x) for x in
                             re.findall(r"<p[ >].*?</p>", re.sub(r"<table.*?</table>", " ", main_html, flags=re.DOTALL),
                                        re.DOTALL))
                 if len(p) >= 60 and "£" not in p
                 and not re.match(r"(Published On|Book|Event (type|times|prices)|Home\b)", p)
                 and "cookie" not in p.lower()]
        text = " ".join(prose)[:3000]
        desc = None
        spec = None
        if len(summary) >= 30:
            desc = summary if len(summary) <= 400 else (summary[:400].rsplit(". ", 1)[0] + ".")
        elif len(text) >= 150:
            prompt = f"""Summarise one UK higher-education event. Respond with strict JSON only.

EVENT TITLE: {title}

PAGE TEXT:
{text}

{{"description": "30-50 word summary using only the text above" or null,
 "specialty": one of "Medical Education", "Leadership & Management" or a clinical specialty if the event is clinical}}"""
            raw = llm_call(prompt)
            if raw:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    try:
                        p = json.loads(m.group(0))
                        desc = (p.get("description") or None)
                        spec = (p.get("specialty") or None)
                    except Exception as e:
                        logger.warning(f"AdvanceHE soft-fields JSON parse failed: {e}")
        if not desc and prose:
            first = prose[0]
            desc = first if len(first) <= 400 else (first[:400].rsplit(". ", 1)[0] + ".")
        out["description"] = desc
        # Deterministic title rules win (keeps labels consistent across the
        # catalogue); the LLM only fills in when the title gives no signal.
        det = self._title_specialty(title)
        spec = det or spec or "Medical Education"
        out["specialty"] = spec
        return out

    @staticmethod
    def _title_specialty(title: str) -> Optional[str]:
        tl = (title or "").lower()
        if any(k in tl for k in _LEADERSHIP_KW):
            return "Leadership & Management"
        return classify_specialty(title, None)
