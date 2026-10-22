"""CNS (Congress of Neurological Surgeons) meetings: Gosuite CMS, JS-rendered listings, bespoke extractor, no LLM.

`cns.org/meetings/calendar` is a month grid that needs a browser and mixes real events with on-demand series and award
windows. The three category listings the calendar is built from render the same events as plain cards
(`div.list-item`: `.title a` -> `/meetings-detail/<slug>`, `.EventStartDate_s`, `.EventEndDate_s`, `.Teaser_s`):
`/meetings/courses`, `/meetings/joint-section-meetings`, `/meetings/other-neurosurgical-meetings` (third-party symposia,
past ones stay listed -> dropped by date). They are rendered with the production browser (`self.browser.navigate`), one
page load each, and nothing is called except the pages themselves.

The Annual Meeting is not in those lists. Its dates come from the static `/meetings/past-and-future-annual-meetings`
("2026: Oct. 31-Nov. 4, Washington, DC"); its microsite `/annualmeeting` holds the venue (`/travel-hotel/location`) and the
fee grids (`/annualmeeting/overview`: a Member and a Non-member table, columns Early Bird / Advanced / Regular with the
window in the header). That microsite always shows the CURRENT edition, so fees, venue and description are attached only to
the edition whose year the fee headers carry; later editions get dates and city only (no stale-edition fees).

Detail pages (`/meetings-detail/<slug>`): "<format> / <title> / <venue | city, state> / <date range>", a Pricing table
("Registration Type | Registration Rate" or two timeframe columns), "Hotel", and the ACCME credit statement. Third-party
events carry a "Visit Website" link; that organiser page is read for public fees with safe_fetch.fetch_validated.

NO AI: cns.org/cns-terms-service forbids feeding CNS content into AI tools. Nothing from this site is sent to
`llm_call`; description is the page/teaser text, specialty is fixed.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from logger import logger

from safe_fetch import check_url_safe, fetch_validated
from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import classify_event_type

_ROOT = "https://www.cns.org"
_LISTINGS = [_ROOT + "/meetings/courses", _ROOT + "/meetings/joint-section-meetings", _ROOT + "/meetings/other-neurosurgical-meetings"]
_ANNUAL_PAGE = _ROOT + "/meetings/past-and-future-annual-meetings"
_SOCIETY = "Congress of Neurological Surgeons (CNS)"
_REQUEST_GAP_S = 1.0
_MAX_FUTURE_DAYS = 550                       # 18 months
_MAX_SPAN_DAYS = 14                          # longer spans are on-demand series and application windows, not events
_US = "United States"
_ACCESS = {"in-person": "in_person", "virtual": "online", "online": "online", "hybrid": "hybrid", "live online": "online"}

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


def _d(s: str) -> Optional[str]:
    """"Jan 16, 2027" -> 2027-01-16."""
    m = re.match(r"^\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})\s*$", s or "")
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def parse_list_items(html: str) -> List[Dict[str, Any]]:
    """Rendered category listing -> [{title, url, start, end, teaser}] (pure)."""
    out: List[Dict[str, Any]] = []
    for m in re.finditer(r'(?s)<div class="list-item">.*?(?=<div class="list-item">|$)', html or ""):
        c = m.group(0)
        t = re.search(r'class="title"><a href="([^"]+)"[^>]*>(.*?)</a>', c)
        def f(k: str) -> str:
            x = re.search(rf'class="{k}">(.*?)</div>', c, re.S)
            return _txt(x.group(1)) if x else ""
        s, e = _d(f("EventStartDate_s")), _d(f("EventEndDate_s"))
        if t and s and e:
            out.append({"title": _txt(t.group(2)), "url": urljoin(_ROOT + "/", t.group(1)), "start": s, "end": e, "teaser": f("Teaser_s")})
    return out


def parse_annual_editions(html: str) -> List[Dict[str, Any]]:
    """/past-and-future-annual-meetings "Future Annual Meetings" lines -> [{year, start, end, city}] (pure)."""
    out: List[Dict[str, Any]] = []
    for l in html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html or "")):
        m = re.match(r"^(20\d\d):\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\s*[\u2013\u2014-]\s*(?:([A-Za-z]{3})[a-z]*\.?\s+)?(\d{1,2}),\s*([^,]+),\s*([A-Z]{2}|DC)$", l)
        if not m:
            continue
        y, m1, d1, m2, d2 = int(m.group(1)), m.group(2).lower(), int(m.group(3)), (m.group(4) or m.group(2)).lower(), int(m.group(5))
        if m1 not in _MONTHS or m2 not in _MONTHS:
            continue
        try:
            start, end = date(y, _MONTHS[m1], d1), date(y, _MONTHS[m2], d2)
        except ValueError:
            continue
        city = m.group(6).strip()
        out.append({"year": y, "start": start.isoformat(), "end": end.isoformat(), "city": f"{city}, DC" if m.group(7) == "DC" else city})
    return out


def parse_detail_page(lines: List[str], title: str) -> Dict[str, Any]:
    """meetings-detail page lines -> format, venue, city, region, credits, description (pure). Reads the block that starts at the
    title line (the CMS chrome before it repeats the site menu)."""
    tl = re.sub(r"\W+", "", title.lower())
    idx = next((i for i, l in enumerate(lines) if re.sub(r"\W+", "", l.lower()) == tl), None)
    out: Dict[str, Any] = {}
    if idx is None:
        return out
    end = next((i for i in range(idx, len(lines)) if lines[i].startswith("The CNS Mission")), len(lines))
    blk = lines[idx:end]
    for l in lines[max(0, idx - 2):idx]:
        if l.lower() in _ACCESS:
            out["event_format"] = _ACCESS[l.lower()]
    for i, l in enumerate(blk[1:8], 1):
        if re.match(r"^[A-Za-z]{3} \d{1,2}, \d{4}\s*-", l):
            break
        if l.lower() in _ACCESS:
            out["event_format"] = _ACCESS[l.lower()]
        elif "|" in l:
            v, loc = [p.strip() for p in l.split("|", 1)]
            out["venue_name"] = v
            cm = re.match(r"^(.+?),\s*([A-Za-z .]+)$", loc)
            if cm:
                out["city"] = cm.group(1).strip()
        else:
            cm = re.match(r"^([A-Z][\w .'-]+),\s*([A-Z]{2})$", l)
            if cm:
                out["city"] = cm.group(1).strip()
    for i, l in enumerate(blk):                                 # third-party page: "Location" then "El Paso, TX"
        if l == "Location" and i + 1 < len(blk):
            cm = re.match(r"^([A-Z][\w .'-]+),\s*([A-Z]{2})$", blk[i + 1])
            if cm:
                out["city"] = cm.group(1).strip()
    if "venue_name" not in out:                                 # "Travel & Hotel" / "Hotel" section: hotel name then its address
        street = r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Way|Place|Plaza|Lane|Parkway|Pkwy)"
        for i, l in enumerate(blk):
            if l in ("Travel & Hotel", "Hotel") and i + 1 < len(blk):
                nxt = blk[i + 1]
                one = re.match(rf"^(?P<v>.+?)\s+\d+\s+.*?\b{street}\s+(?P<c>[A-Z][\w .'-]+?),\s*[A-Z]{{2}}\s+\d{{5}}", nxt)
                if one:                                         # name + address run together on one line
                    out["venue_name"], out["city"] = one.group("v").strip(), one.group("c").strip()
                elif len(nxt) < 70 and not re.search(r"[.!?]$", nxt):
                    out["venue_name"] = nxt
                    for a in blk[i + 2:i + 5]:
                        am = re.match(r"^([A-Z][\w .'-]+),\s*([A-Z]{2})\s+\d{5}", a)
                        if am:
                            out.setdefault("city", am.group(1).strip())
                            break
                break
    text = " ".join(blk)
    cm = re.search(r"maximum of ([\d.]+) AMA PRA Category 1", text)
    if cm:
        out["cpd_points"] = float(cm.group(1))
    if out.get("cpd_points") or re.search(r"(?i)accredited by the Accreditation Council for Continuing Medical Education", text):
        out["cpd_accredited"] = True
    for i, l in enumerate(blk):
        if l in ("Course Description", "Description", "About The Event") and i + 1 < len(blk) and len(blk[i + 1]) >= 60:
            out["description"] = blk[i + 1][:600]
            break
    return out


def external_fee_tiers(html: str) -> List[Dict[str, Any]]:
    """Third-party organiser page: a "REGISTRATION FEES:" heading then "<category> $1,500.00 *note" lines (pure)."""
    lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer)\b.*?</\1\s*>", " ", html or ""))
    tiers: List[Dict[str, Any]] = []
    on = False
    for l in lines:
        if re.match(r"(?i)^registration fees?\s*:?$", l):
            on = True
            continue
        if on:
            m = re.match(r"^(.{3,60}?)\s+\$\s*([\d,]+(?:\.\d{2})?)\b", l)
            if not m:
                if tiers:
                    break
                continue
            tiers.append({"tier_label": f"Registration \u00b7 {m.group(1).strip(' :')}"[:120], "price_gbp": float(m.group(2).replace(",", "")),
                          "currency": "USD", "is_early_bird": False, "early_bird_deadline": None})
    return tiers


class CnsExtractor(BaseExtractor):
    DEFAULT_SPECIALTY = "Neurosurgery"

    # ---- Phase A -----------------------------------------------------------
    def _render(self, url: str) -> Optional[str]:
        br = getattr(self, "browser", None)
        if br is None or getattr(br, "page", None) is None:
            logger.warning("CNS: no browser available; listings need JS")
            return None
        try:
            br.navigate(url)
            try:
                br.page.wait_for_selector("div.list-item", timeout=15000)
            except Exception:                                   # noqa: BLE001  (an empty category has no cards)
                pass
            br.page.wait_for_timeout(1500)
            return br.page.content()
        except Exception as e:                                  # noqa: BLE001
            logger.warning(f"CNS: listing {url} failed: {e}")
            return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen = set()
        listed_any = False
        for n, url in enumerate(_LISTINGS):
            if n:
                time.sleep(_REQUEST_GAP_S)
            html = self._render(url)
            if html is None:
                continue
            listed_any = True
            items = parse_list_items(html)
            tot = re.search(r"\d+\s*-\s*\d+ of (\d+) results", html)
            if tot and int(tot.group(1)) > len(items):
                logger.warning(f"CNS: {url} shows {tot.group(1)} results but {len(items)} cards were read (pagination not followed)")
            for r in items:
                s, e = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
                if e < today:
                    continue
                if (e - s).days > _MAX_SPAN_DAYS:
                    logger.info(f"CNS: {r['title']!r} spans {(e - s).days} days (series/window), skipped")
                    continue
                if (s - today).days > _MAX_FUTURE_DAYS:
                    continue
                if r["url"] in seen or re.search(r"(?i)cancel", r["title"]):
                    continue
                seen.add(r["url"])
                shells.append({"title": r["title"], "booking_url": r["url"], "source_url": r["url"], "start_date": r["start"], "end_date": r["end"],
                               "start_time": None, "venue_raw": None, "category": r["teaser"] or None, "_kind": "detail", "_teaser": r["teaser"]})
        time.sleep(_REQUEST_GAP_S)
        ahtml = fetch_html(_ANNUAL_PAGE, browser=getattr(self, "browser", None))
        for r in parse_annual_editions(ahtml or ""):
            if date.fromisoformat(r["end"]) < today or (date.fromisoformat(r["start"]) - today).days > _MAX_FUTURE_DAYS:
                continue
            u = f"{_ROOT}/annualmeeting#{r['year']}"
            shells.append({"title": f"{r['year']} CNS Annual Meeting", "booking_url": u, "source_url": u, "start_date": r["start"], "end_date": r["end"],
                           "start_time": None, "venue_raw": None, "category": None, "_kind": "annual", "_year": r["year"], "_city": r["city"]})
        if not shells and not listed_any:
            return None
        shells.sort(key=lambda s: s["start_date"])
        logger.info(f"CNS: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    @staticmethod
    def _body_lines(html: str) -> List[str]:
        return html_to_lines(re.sub(r"(?s)<!--.*?-->", " ", re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1\s*>", " ", html or "")))

    def _annual_detail(self, shell: Dict[str, Any], html: str, out: Dict[str, Any]) -> None:
        yr = shell["_year"]
        out["event_type"], out["event_format"], out["region"] = "conference", "in_person", _US
        out["city"] = shell.get("_city")
        time.sleep(_REQUEST_GAP_S)
        ov = fetch_html(_ROOT + "/annualmeeting/overview", browser=getattr(self, "browser", None))
        if not ov:
            return
        heads = " ".join(_txt(h) for h in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr\s*>", " ".join(re.findall(r"(?is)<table\b.*?</table\s*>", ov))[:6000])[:1])
        if not re.search(rf"\b{yr}\b|/{str(yr)[2:]}\b", heads):    # the fee grids describe another edition (site shows the current one)
            logger.info(f"CNS: annual fee grids are not for {yr} (headers: {heads[:80]!r}); fees skipped")
            return
        tiers = grid_tiers(ov, currency="USD", ref_year=yr)
        if tiers:
            out["pricing_tiers"] = tiers
        time.sleep(_REQUEST_GAP_S)
        loc = fetch_html(_ROOT + "/annualmeeting/travel-hotel/location", browser=getattr(self, "browser", None))
        lm = re.search(r"will be held at the (.{5,80}?)!", _txt(loc or ""))
        if lm:
            out["venue_name"] = lm.group(1).strip()
        for l in self._body_lines(html):
            if l.startswith(f"The {yr} CNS Annual Meeting") and len(l) >= 80:
                out["description"] = l[:600]
                break
        out["cpd_accredited"] = True

    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        start, end = shell["start_date"], shell.get("end_date") or shell["start_date"]
        out: Dict[str, Any] = {"society": _SOCIETY, "specialty": self.DEFAULT_SPECIALTY, "start_date": start, "end_date": end}
        if shell.get("_kind") == "annual":
            if str(date.fromisoformat(start).year) == str(shell["_year"]):
                # the microsite is the CURRENT edition; a later edition keeps dates + city only
                cur = re.search(r"(\d{4}) CNS Annual Meeting", _txt(html))
                if cur and int(cur.group(1)) == shell["_year"]:
                    self._annual_detail(shell, html, out)
                else:
                    out.update(event_type="conference", event_format="in_person", region=_US, city=shell.get("_city"))
            return out
        lines = self._body_lines(html)
        d = parse_detail_page(lines, shell["title"])
        out["event_type"] = classify_event_type(shell["title"], "")
        for k in ("event_format", "venue_name", "city", "cpd_points", "cpd_accredited"):
            if d.get(k) is not None:
                out[k] = d[k]
        teaser = re.sub(r"(?i)^save the date!\s*", "", shell.get("_teaser") or "").strip()
        if not out.get("city"):                                 # CNS's own teaser: "..., in Phoenix!" / "at the Hilton Union Square, San Francisco, CA!"
            tm = re.search(r"\bat the ([^,]+),\s*([A-Z][\w .'-]+),\s*[A-Z]{2}!$", teaser) or re.search(r"(?:,|\s)in ()([A-Z][\w .'-]+)!$", teaser)
            if tm:
                out["city"] = tm.group(2).strip()
                if tm.group(1) and not out.get("venue_name"):
                    out["venue_name"] = tm.group(1).strip()
        if out.get("city") and out.get("event_format") != "online":
            out["region"] = _US
            out.setdefault("event_format", "in_person")
        desc = d.get("description") or ("" if re.match(r"(?i)save the date|for the \d{4}|join us for the \d{4}", teaser) else teaser)
        if len(desc) >= 60:
            out["description"] = desc[:600]
        # ---- fees: the page's own pricing table, else the third-party organiser's public fee list
        tiers = grid_tiers(html, currency="USD", ref_year=date.fromisoformat(start).year)
        organiser = None
        for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""", html):
            if re.search(r"(?i)visit website|register", _txt(m.group(2))) and (urlparse(m.group(1)).hostname or "").lower().rstrip(".") not in ("cns.org", "www.cns.org", "mcievents.com", "www.mcievents.com"):
                organiser = _html.unescape(m.group(1))
                break
        if organiser:
            out["organiser_url"] = organiser
        if not tiers and organiser and shell["booking_url"].rsplit("/", 1)[-1].startswith("new-calendarevent"):
            ok, why = check_url_safe(organiser)
            if not ok:
                logger.warning(f"CNS: organiser link refused ({why}): {organiser}")
            else:
                time.sleep(_REQUEST_GAP_S)
                verdict, _final, body, enc, status = fetch_validated(organiser, deadline=time.monotonic() + 30, max_bytes=2_000_000)
                if verdict == "ok" and body:
                    ext = body.decode(enc or "utf-8", errors="replace")
                    if str(date.fromisoformat(start).year) in _txt(ext):        # the organiser page names this edition's year
                        tiers = external_fee_tiers(ext)
                else:
                    logger.warning(f"CNS: organiser page not used (verdict={verdict}, status={status}): {organiser}")
        if tiers:
            out["pricing_tiers"] = tiers
        return out
