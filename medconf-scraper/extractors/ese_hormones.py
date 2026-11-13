"""European Society of Endocrinology (ese-hormones.org): Umbraco site, "Events & Key Dates" listing rendered by a Vue app from a JSON API.

The listing page `/education-and-training/events-key-dates/` shows 9 cards a page; the cards come from
`POST /umbraco/api/searchapi/search` with `{"filters":[],"pageNumber":N,"filterConfigurationId":"9081","rootNodeIds":[8010],
"resultsPerPage":50,"orderByDescending":false}` and answer `{TotalItemCount, Results[], TotalPages}`; one result is
`{Name, Url, Description, TagGroupContentType[], TagGroupFocusArea[], EventStartDate{Day,Month,Year}, EventEndDate, Location}` and the
default (no filter) result is the upcoming events only. The API is called from inside the loaded listing page (same origin, same
cookies as a visitor's browser), so no challenge is replayed. If it fails, no shell is returned (never a DOM guess).

Relevance: patient forums, awareness days and key-date/deadline entries are for patients or administration and are dropped (logged);
clinician courses, congresses, webinars and external (endorsed) meetings stay. Detail `/<slug>/`: an intro, optional fee grid
(`pricing_tables`), a REGISTER link to the registrar and a "Website" link for external events.
"""
import html as html_lib
import json
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import money
import robots_gate
from logger import logger

from .abstract_classifier import classify_submission
from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .specialty_classifier import classify_specialty
from .tribe_events import html_to_lines

ROOT = "https://www.ese-hormones.org"
LISTING_URL = ROOT + "/education-and-training/events-key-dates/"
API_PATH = "/umbraco/api/searchapi/search"
SOCIETY = "ESE"
DEFAULT_SPECIALTY = "Diabetes & Endocrinology"
PAGE_SIZE = 50
MAX_PAGES = 6

_JS_SEARCH = """async ([n, size]) => {
  const r = await fetch('%s', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({filters: [], pageNumber: n, filterConfigurationId: '9081', rootNodeIds: [8010],
                          resultsPerPage: size, orderByDescending: false})});
  return await r.text();
}""" % API_PATH

_DROP_TYPES = {"patient forums", "awareness days", "deadlines", "key dates"}
_ONLINE_RE = re.compile(r"(?i)\b(online|virtual|webinar)\b")
_HYBRID_RE = re.compile(r"(?i)\bhybrid\b|in[- ]person\b[^.]{0,40}\band (?:also )?online|in[- ]person or online|online and in[- ]person")
_CTA_RE = re.compile(r"(?i)regist|website|more information|event website|book")


def _api_date(o: Any) -> Optional[str]:
    try:
        return date(int(o["Year"]), int(o["Month"]), int(o["Day"])).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def parse_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """API payload -> [{title, url, start_date, end_date, location, types, description}]. Pure."""
    out = []
    for r in (payload or {}).get("Results") or []:
        start = _api_date(r.get("EventStartDate"))
        if not r.get("Name") or not r.get("Url") or not start:
            continue
        end = _api_date(r.get("EventEndDate"))
        out.append({"title": html_lib.unescape(r["Name"]).strip(), "url": ROOT + r["Url"], "start_date": start,
                    "end_date": end if end and end != start else None, "location": (r.get("Location") or "").strip() or None,
                    "types": [t.get("name", "") for t in (r.get("TagGroupContentType") or [])],
                    "description": (r.get("Description") or "").strip() or None})
    return out


def is_relevant(types: List[str]) -> bool:
    return not any(t.strip().lower() in _DROP_TYPES for t in types or [])


def split_location(raw: Optional[str]) -> Dict[str, Any]:
    """'Annecy, France' / 'ALFÂNDEGA DO PORTO, Porto, Portugal' / 'Online' -> venue/city/region/format. Pure."""
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    if not parts:
        return {}
    if len(parts) == 1:
        return {"event_format": "online"} if _ONLINE_RE.search(parts[0]) else {"event_format": "in_person", "city": parts[0][:80]}
    out: Dict[str, Any] = {"event_format": "in_person", "region": parts[-1][:80], "city": parts[-2][:80]}
    if len(parts) > 2:
        out["venue_name"] = ", ".join(parts[:-2])[:200]
    return out


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_EARLY_DEADLINE_RE = re.compile(
    r"(?i)early[ -]?bird\s+deadline\s*:?\s*(?:(?:mon|tues?|wednes|thurs?|fri|satur|sun)day\s+)?(\d{1,2})\s+(%s)\s+(20\d\d)" % "|".join(_MONTHS))


def _cell_lines(cell_html: str) -> List[str]:
    return [re.sub(r"[\u200b\xa0\s]+", " ", l).strip() for l in html_to_lines(cell_html)]


def parse_fee_grid(html: str, page_text: str = "") -> List[Dict[str, Any]]:
    """The ESE two-header-row fee grid: row 1 = categories ('ESE member', 'Non-member'), row 2 = timeframes ('Before / After Early Bird
    deadline'), then one row per attendance mode ('In-person ...', 'Online') with one price per column. -> one tier per price, label
    `Mode · Category · Timeframe`, early-bird columns flagged with the page's 'Early Bird deadline: <date>'. Pure; [] when no grid."""
    tiers: List[Dict[str, Any]] = []
    dm = _EARLY_DEADLINE_RE.search(page_text or "")
    deadline = None
    if dm:
        try:
            deadline = date(int(dm.group(3)), _MONTHS[dm.group(2).lower()], int(dm.group(1))).isoformat()
        except ValueError:
            deadline = None
    for tm in re.finditer(r"(?is)<table\b.*?</table>", html or ""):
        rows = [[_cell_lines(c) for c in re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", tr)]
                for tr in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", tm.group(0))]
        rows = [r for r in rows if r]
        first = next((i for i, r in enumerate(rows) if sum(1 for c in r[1:] if money.parse_amount(" ".join(c))) >= 2), None)
        if first is None or first == 0 or first > 2:
            continue
        n = len(rows[first]) - 1
        heads = [[" ".join(c) for c in r][-n:] for r in rows[:first] if len(r) >= n]
        if not heads or any(len(h) != n for h in heads):
            continue
        for r in rows[first:]:
            if len(r) != n + 1 or not r[0]:
                continue
            mode = r[0][0]
            for j in range(n):
                m = money.parse_amount(" ".join(r[1 + j]))
                if m is None or not m.currency or m.high is not None or m.amount <= 0:
                    continue
                parts = []
                for h in heads:
                    if h[j] and h[j] not in parts:
                        parts.append(h[j])
                early = any(re.match(r"(?i)before early", p) for p in parts)
                tiers.append({"tier_label": " · ".join([mode] + parts)[:200], "price_gbp": m.amount, "currency": m.currency,
                              "is_early_bird": early, "early_bird_deadline": deadline if early else None})
    return tiers


def abstract_fields(lines: List[str], start_iso: Optional[str]) -> Dict[str, Any]:
    """Abstract status from the event page's own text lines (one line per cell keeps 'Abstract Submission Deadline' next to its date).
    Open only with a future deadline or explicit open wording; a programme with no date gives a note. Pure."""
    try:
        start = date.fromisoformat(start_iso) if start_iso else None
    except ValueError:
        start = None
    is_open, deadline, note = classify_submission("\n".join(lines), date.today(), start)
    out: Dict[str, Any] = {}
    if deadline:
        out["abstract_open"], out["abstract_deadline"] = is_open, deadline.isoformat()
    elif note:
        out["abstract_open"], out["abstract_deadline_note"] = is_open, note
    return out


class EseHormonesExtractor(BaseExtractor):

    def _search(self, page, n: int) -> Optional[Dict[str, Any]]:
        try:
            txt = page.evaluate(_JS_SEARCH, [n, PAGE_SIZE])
            return json.loads(txt)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ESE: search API page {n} failed: {e}")
            return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        b = getattr(self, "browser", None)
        if b is None or not robots_gate.allowed(ROOT + API_PATH):
            logger.warning("ESE: no browser or API disallowed; no shells")
            return []
        try:
            b.navigate(LISTING_URL)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ESE: listing navigation failed: {e}")
            return []
        today = date.today().isoformat()
        rows: List[Dict[str, Any]] = []
        api_ok = False
        total_items = None
        for n in range(1, MAX_PAGES + 1):
            payload = self._search(b.page, n)
            if payload is None:
                break
            api_ok = True
            total_items = payload.get("TotalItemCount", total_items)
            got = parse_results(payload)
            rows.extend(got)
            if n >= int(payload.get("TotalPages") or 1) or not payload.get("Results"):
                break
        shells: List[Dict[str, Any]] = []
        seen = set()
        for r in rows:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            if r["start_date"] < today:
                logger.info(f"ESE: dropped {r['title']!r} (start {r['start_date']})")
                continue
            if not is_relevant(r["types"]):
                logger.info(f"ESE: dropped {r['title']!r} (not clinician CPD: {r['types']})")
                continue
            shells.append({"title": r["title"], "booking_url": r["url"], "start_date": r["start_date"], "end_date": r["end_date"],
                           "venue_raw": r["location"], "description": r["description"], "_types": r["types"]})
        logger.info(f"ESE: {len(shells)} kept of {len(rows)} listed (API total {total_items})")
        if api_ok and total_items == 0:
            self.verified_empty = "ESE events API answered with zero upcoming events"
        return shells

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        html = ""
        try:
            html = page.content() if page is not None else ""
        except Exception:
            html = ""
        if "<h1" not in html:
            html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) or html
        title = shell.get("title") or ""
        out: Dict[str, Any] = {"society": SOCIETY}
        out.update(split_location(shell.get("venue_raw")))

        m = re.search(r'(?is)(?:<h1[^>]*>|<span class=["\']text-6xl[^"\']*["\']>)(.*?)</(?:h1|span)>(.*?)(?:>\s*Published\b|<footer)', html)
        body = m.group(2) if m else ""
        lines = [l for l in html_to_lines(re.sub(r"\s*\n\s*", " ", body))]
        body_text = " ".join(lines)
        if _HYBRID_RE.search(body_text) and out.get("event_format") == "in_person":
            out["event_format"] = "hybrid"

        desc = shell.get("description") if len(shell.get("description") or "") >= 60 else None
        desc = desc or next((l for l in lines if len(l) >= 60 and re.match(r"[A-Za-z\"'(0-9]", l)
                             and not re.match(r"(?i)^(save the date|registration|warning|early bird)", l)), None)
        if desc:
            if len(desc) > 400:
                cut = desc[:400]
                idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
                desc = cut[:idx + 1] if idx >= 150 else cut.rstrip() + "..."
            out["description"] = desc

        tiers = (parse_fee_grid(body, body_text) or parse_pricing_tables(body, default_currency="")) if body else []
        if tiers:
            out["pricing_tiers"] = tiers

        org = None
        for am in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a>""", body):
            href, txt = html_lib.unescape(am.group(1)), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", am.group(2))).strip()
            if _CTA_RE.search(txt) and not href.startswith(ROOT) and "mailto:" not in href:
                org = href
                break
        if org:
            out["organiser_url"] = org

        if re.search(r"(?i)\bEACCME\b", body_text):
            out["cpd_accredited"] = True
        out.update(abstract_fields(lines, shell.get("start_date")))
        out["specialty"] = classify_specialty(title) or DEFAULT_SPECIALTY
        return out
