"""AAD (American Academy of Dermatology) meetings and courses: bespoke extractor, no LLM.

The recon URL (`/member/meetings/events/locations`) is only the dates page: "Annual Meeting 2027: San Francisco, California,
March 19-23 / 2028: Washington, D.C., March 17-21" and "Save the date for these summer educational meetings: July 22-25, 2027:
Chicago, IL". The public meetings listing is `/member/meetings/events`, a card deck: DermCatalyst (2026 edition postponed, no
date -> skipped), Hands-On: Cosmetics (own page: "Oct. 24-25, 2026, Chicago IL / Palmer House Hilton", "Rates" lines), the
2027 Annual Meeting microsite (`/member/meetings-education/am27`, fees at `/registration/fees` as a public grid: Early bird /
Standard) and non-event cards (session-director deadlines, board meetings, a third-party calendar) that are ignored. Editions
with no page of their own (Annual 2028, the summer meeting) get a shell from the dates page with the dates page as URL.

Fees are read only from a page that names the edition ("2027 AAD Annual Meeting"). Hands-On: Cosmetics rates are shown
publicly but "registration is open to AAD members only", so the tier labels say so.

NO AI: aad.org/terms-use forbids incorporating Academy content into any AI learning model without written permission.
Nothing from this site is sent to `llm_call`; description is the page's own meta/intro text, specialty is fixed.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import find_dates

_ROOT = "https://www.aad.org"
_LOCATIONS = _ROOT + "/member/meetings/events/locations"
_EVENTS = _ROOT + "/member/meetings/events"
_SOCIETY = "American Academy of Dermatology (AAD)"
_REQUEST_GAP_S = 1.0
_MAX_FUTURE_DAYS = 550                       # 18 months
_NOT_EVENT_SLUGS = {"direct", "locations", "career-launch-on-demand"}
_US = "United States"

# ---- public fee grids (header row "Registration Category/Type | <column> | <column>") -> tiers -----------------------------
_GRID_LEAD_RE = re.compile(r"(?i)registration\s+(?:category|type)")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DEADLINE_RE = re.compile(
    r"(?i)(?:ends?|on or before|before|register by|until|through)\s*:?\s*"
    r"(?:(\d{1,2})/(\d{1,2})/(\d{2,4})|([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?)")


def _cell_txt(frag: str) -> str:
    frag = re.sub(r"(?is)<sup\b.*?</sup\s*>", " ", frag)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", frag)).replace("\xa0", " ").replace("﻿", "")
    return re.sub(r"\s+", " ", t).strip()


def _grid_price(s: str) -> Optional[float]:
    s = s.strip()
    if re.match(r"(?i)^(?:no charge|complimentary|free)\b", s):
        return 0.0
    m = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", s)
    return float(m.group(1).replace(",", "")) if m else None


def _deadline_iso(text: str, ref_year: int) -> Optional[str]:
    """First 'ends/by/before <date>' in text -> ISO. A date without a year takes ref_year."""
    m = _DEADLINE_RE.search(text or "")
    if not m:
        return None
    try:
        if m.group(1):
            y = int(m.group(3))
            return date(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2))).isoformat()
        mon = _MONTHS.get(m.group(4).lower())
        return date(int(m.group(6)) if m.group(6) else ref_year, mon, int(m.group(5))).isoformat() if mon else None
    except ValueError:
        return None


def grid_tiers(html: str, *, currency: str, ref_year: int, section_for=None, page_text: str = "") -> List[Dict[str, Any]]:
    """Every public fee grid on the page. Column headers become the timeframe/option; deadlines come from the header
    ('Ends January 4, 2027', 'Received on or before 5/31/2026'), else from the 'early bird ... until <date>' sentence."""
    out: List[Dict[str, Any]] = []
    for tm in re.finditer(r"(?is)<table\b[^>]*>(.*?)</table\s*>", html or ""):
        rows = re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr\s*>", tm.group(1))
        cells = [re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", r) for r in rows]
        hi = next((k for k, r in enumerate(cells[:3]) if r and _GRID_LEAD_RE.search(_cell_txt(r[0]))), None)
        if hi is None:                                          # the header row may sit under a one-line banner ("2026 RATES")
            continue
        cells = cells[hi:]
        if len(cells) < 2:
            continue
        ctx = _cell_txt(html[max(0, tm.start() - 900):tm.start()])[-600:]
        section = section_for(ctx) if section_for else "Registration"
        heads = [_cell_txt(c) for c in cells[0]]
        cols: Dict[int, Dict[str, Any]] = {}
        for i, h in enumerate(heads[1:], 1):
            name = re.sub(r"\s*\(.*$", "", h)
            name = re.split(r"(?i)\breceived\b|\bbeginning\b|\bbegins\b|\bends?\b|:", name)[0].strip(" :-*")
            if re.fullmatch(r"(?i)(?:registration )?(?:rate|fee|price)", name):
                name = ""
            early = bool(re.search(r"(?i)early|advance|register by", h))
            dl = _deadline_iso(h, ref_year)
            nr = re.search(r"(?i)between\s+\d{1,2}/\d{1,2}/\d{2,4}\s*[-\u2013]\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", h)
            if early and not dl and nr:                                          # "Received between 6/1/2026- 9/30/26": the window's end
                try:
                    yy = int(nr.group(3))
                    dl = date(yy + 2000 if yy < 100 else yy, int(nr.group(1)), int(nr.group(2))).isoformat()
                except ValueError:
                    dl = None
            if early and not dl and page_text:
                m = re.search(r"(?i)(?:early[- ]bird|advance)[^.]{0,90}?(?:until|ends?|before)\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", page_text)
                if m and m.group(1).lower() in _MONTHS:
                    try:
                        dl = date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
                    except ValueError:
                        dl = None
            cols[i] = {"name": name.title() if name.isupper() else name, "early": early, "deadline": dl if early else None}
        if cols and not any(re.search(r"(?i)advance|early|late|regular|standard|on-?site|register", c["name"]) for c in cols.values()):
            tm2 = re.search(r"(?i)\b(advance|early[- ]bird|late|on-?site)\b[^.]{0,25}registration", ctx[-450:])
            if tm2:                                                 # timeframe stated once above the grid
                adv = bool(re.match(r"(?i)advance|early", tm2.group(1)))
                dl = _deadline_iso(ctx[-450:], ref_year) if adv else None
                for c in cols.values():
                    c.update(tf="Advance" if adv else "Late/On-site", early=adv, deadline=dl)
        for row in cells[1:]:
            if len(row) < 2:
                continue
            strong = re.search(r"(?is)<strong\b[^>]*>(.*?)</strong\s*>", row[0])
            cat = _cell_txt(strong.group(1) if strong else row[0]).strip(" *†‡§:")
            if not cat:
                continue
            for i, col in cols.items():
                p = _grid_price(_cell_txt(row[i])) if i < len(row) else None
                if p is None:
                    continue
                label = " · ".join(x for x in (section, cat[:70], col["name"][:40], col.get("tf")) if x)[:120]
                out.append({"tier_label": label, "price_gbp": p, "currency": currency, "is_early_bird": col["early"],
                            "early_bird_deadline": col["deadline"]})
    seen, uniq = set(), []
    for t in out:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def _lines(html: str) -> List[str]:
    return html_to_lines(re.sub(r"(?s)<!--.*?-->", " ", re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer|aside)\b.*?</\1\s*>", " ", html or "")))


def parse_locations(html: str) -> List[Dict[str, Any]]:
    """Dates page -> [{kind: annual|summer, year, start, end, city, region}] (pure)."""
    out: List[Dict[str, Any]] = []
    lines = _lines(html)
    for l in lines:
        m = re.match(r"^(20\d\d):\s*([^,]+),\s*([^,]+),\s*([A-Z][a-z]+\.? \d{1,2}\s*[\u2013-]\s*\d{1,2})$", l)
        if m:
            ds = find_dates(f"{m.group(4)}, {m.group(1)}")
            if ds:
                out.append({"kind": "annual", "year": int(m.group(1)), "start": ds[0]["start"], "end": ds[0]["end"],
                            "city": f"{m.group(2).strip()}, DC" if "D.C" in m.group(3) else m.group(2).strip(), "region": _US})
            continue
        m = re.match(r"^([A-Z][a-z]+\.? \d{1,2}\s*[\u2013-]\s*\d{1,2}),\s*(20\d\d):\s*([^,]+),\s*([A-Z]{2})$", l)
        if m:
            ds = find_dates(f"{m.group(1)}, {m.group(2)}")
            if ds:
                out.append({"kind": "summer", "year": int(m.group(2)), "start": ds[0]["start"], "end": ds[0]["end"], "city": m.group(3).strip(), "region": _US})
    return out


def parse_event_cards(html: str) -> List[Dict[str, str]]:
    """/member/meetings/events card deck -> [{title, url}] for event pages only (pure)."""
    out: List[Dict[str, str]] = []
    for m in re.finditer(r'(?is)<a\b[^>]*href="(https://www\.aad\.org/member/meetings(?:-education)?/[^"]+)"[^>]*class="card-title[^"]*"[^>]*>(.*?)</a>', html or ""):
        url, title = m.group(1), _txt(m.group(2))
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug in _NOT_EVENT_SLUGS or not (re.search(r"/events/[^/]+$", url) or re.search(r"/meetings-education/am\d\d$", url)):
            continue
        out.append({"title": title, "url": url})
    return out


def parse_hands_on(html: str) -> Dict[str, Any]:
    """Hands-On: Cosmetics style page -> date/city/venue/rates/credits (pure)."""
    lines = _lines(html)
    out: Dict[str, Any] = {}
    for i, l in enumerate(lines):
        ds = find_dates(l) if len(l) < 70 else []
        if ds and re.search(r"20\d\d,\s*[A-Z]", l):
            out["start"], out["end"] = ds[0]["start"], ds[0]["end"]
            m = re.search(r"20\d\d,\s*([A-Z][A-Za-z .'-]+?)\s+([A-Z]{2})\s*$", l)
            if m:
                out["city"] = m.group(1).strip()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt and len(nxt) < 60 and not re.search(r"[.!?]$", nxt):
                out["venue"] = nxt
            break
    rates = []
    for l in lines:
        m = re.match(r"^((?:Resident )?Standard Registration Rate)\s*:?\s*\$\s*([\d,]+(?:\.\d{2})?)$", l)
        if m:
            rates.append((m.group(1), float(m.group(2).replace(",", ""))))
    out["rates"] = rates
    cm = re.search(r"maximum of ([\d.]+) AMA PRA Category 1", " ".join(lines))
    if cm:
        out["credits"] = float(cm.group(1))
    out["members_only"] = bool(re.search(r"(?i)open to AAD members only", " ".join(lines)))
    out["postponed"] = bool(re.search(r"(?i)\bpostponed\b", " ".join(lines[:60])))
    return out


class AadExtractor(BaseExtractor):
    DEFAULT_SPECIALTY = "Dermatology"

    # ---- Phase A -----------------------------------------------------------
    def _get(self, url: str) -> Optional[str]:
        for attempt in range(3):
            body = fetch_html(url, browser=getattr(self, "browser", None))
            if body and len(body) > 1500:
                return body
            logger.warning(f"AAD fetch attempt {attempt + 1}/3 failed for {url}")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        loc_html = self._get(_LOCATIONS)
        if not loc_html:
            return None
        locs = parse_locations(loc_html)
        time.sleep(_REQUEST_GAP_S)
        ev_html = self._get(_EVENTS)
        cards = parse_event_cards(ev_html) if ev_html else []
        shells: List[Dict[str, Any]] = []

        def keep(start: str, end: str, what: str) -> bool:
            if date.fromisoformat(end) < today:
                return False
            if (date.fromisoformat(start) - today).days > _MAX_FUTURE_DAYS:
                logger.info(f"AAD: {what} beyond the 18-month horizon, skipped")
                return False
            return True

        for c in cards:
            m = re.search(r"/meetings-education/am(\d\d)$", c["url"])
            if m:                                                   # the Annual Meeting microsite; dates from the dates page
                yr = 2000 + int(m.group(1))
                loc = next((l for l in locs if l["kind"] == "annual" and l["year"] == yr), None)
                if loc and keep(loc["start"], loc["end"], f"Annual {yr}"):
                    shells.append({"title": f"{yr} AAD Annual Meeting", "booking_url": c["url"], "source_url": c["url"], "start_date": loc["start"],
                                   "end_date": loc["end"], "start_time": None, "venue_raw": None, "category": None, "_kind": "annual",
                                   "_city": loc["city"], "_region": loc["region"]})
                continue
            time.sleep(_REQUEST_GAP_S)
            page_html = self._get(c["url"])
            info = parse_hands_on(page_html) if page_html else {}
            if info.get("postponed") or not info.get("start"):
                logger.info(f"AAD: {c['title']} skipped (postponed or no dated edition)")
                continue
            if not keep(info["start"], info["end"], c["title"]):
                continue
            shells.append({"title": c["title"], "booking_url": c["url"], "source_url": c["url"], "start_date": info["start"], "end_date": info["end"],
                           "start_time": None, "venue_raw": None, "category": None, "_kind": "course", "_city": info.get("city"), "_region": _US})
        have_annual = {s["start_date"][:4] for s in shells if s["_kind"] == "annual"}
        for l in locs:                                              # editions with no page of their own
            if l["kind"] == "annual" and str(l["year"]) in have_annual:
                continue
            if not keep(l["start"], l["end"], f"{l['kind']} {l['year']}"):
                continue
            name = f"{l['year']} AAD Annual Meeting" if l["kind"] == "annual" else f"AAD Summer Educational Meeting {l['year']}"
            url = f"{_LOCATIONS}#{l['kind']}-{l['year']}"
            shells.append({"title": name, "booking_url": url, "source_url": url, "start_date": l["start"], "end_date": l["end"], "start_time": None,
                           "venue_raw": None, "category": None, "_kind": f"{l['kind']}_nopage", "_city": l["city"], "_region": l["region"]})
        logger.info(f"AAD: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        kind = shell.get("_kind")
        start, end = shell["start_date"], shell.get("end_date") or shell["start_date"]
        out: Dict[str, Any] = {"society": _SOCIETY, "specialty": self.DEFAULT_SPECIALTY, "start_date": start, "end_date": end,
                               "event_type": "course" if kind == "course" else "conference", "region": shell.get("_region") or _US}
        if shell.get("_city"):
            out["city"] = shell["_city"]
        if kind in ("annual", "course"):
            out["event_format"] = "in_person"
        if kind in ("annual_nopage", "summer_nopage"):              # the page is the dates page: nothing else is known
            out["event_format"] = "in_person"
            return out
        plain = " ".join(_lines(html))
        md = re.search(r"""(?i)<meta\b[^>]*name=["']description["'][^>]*content=["']([^"']*)""", html)
        desc = re.sub(r"\s+", " ", _html.unescape(md.group(1))).strip() if md else ""
        if kind == "course":
            info = parse_hands_on(html)
            if info.get("start") == start:                          # the page still describes this edition
                if info.get("venue"):
                    out["venue_name"] = info["venue"]
                if info.get("credits"):
                    out["cpd_points"], out["cpd_accredited"] = info["credits"], True
                suffix = " (AAD members only)" if info.get("members_only") else ""
                tiers = [{"tier_label": f"Registration \u00b7 {lbl}{suffix}"[:120], "price_gbp": price, "currency": "USD",
                          "is_early_bird": False, "early_bird_deadline": None} for lbl, price in info.get("rates", [])]
                if tiers:
                    out["pricing_tiers"] = tiers
            if not desc:
                desc = next((l for l in _lines(html) if re.match(r"^Join us this fall", l)), "")
        else:                                                       # annual meeting microsite: fees on /registration/fees
            yr = date.fromisoformat(start).year
            if re.search(r"(?i)accredited by the Accreditation Council for Continuing Medical Education", plain):
                out["cpd_accredited"] = True
            time.sleep(_REQUEST_GAP_S)
            fee_html = self._get(shell["booking_url"].rstrip("/") + "/registration/fees")
            if fee_html and f"{yr} AAD Annual Meeting" in _txt(fee_html):
                ptxt = _txt(re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", fee_html))
                tiers = grid_tiers(fee_html, currency="USD", ref_year=yr, page_text=ptxt)
                if tiers:
                    out["pricing_tiers"] = tiers
        if len(desc) >= 60:
            out["description"] = desc[:600]
        return out
