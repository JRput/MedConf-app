"""
ISUOG (International Society of Ultrasound in Obstetrics and Gynecology) —
events extractor.

Static, server-rendered Preside CMS site; no JS needed for listing or detail.

LISTING (https://www.isuog.org/events/events-calendar.html):
One page. The "Upcoming events" tab (`#tab-upcoming-article-list`) holds every
future event as `<div class="article-block">` cards (title link, `span.date`
"Oct 11, 2026", `a.category`, `span.location`). The page states its own total
("19 events found") which we check against the parsed count. The "Past events"
tab (`#tab-past-article-list`, `article-block-past-event`) is lazy-loaded
history — we cut the HTML at it and never read it. No pagination. The default
view already spans several years (2027 events are present); `?year=` only
filters it down.

DETAIL (https://www.isuog.org/event/<slug>.html) — two shapes:

  A) ISUOG Approved Courses (run by third-party organisers): `h1.page-title`
     is the title; `.entry-meta` holds date range ("25-29 January 2027", also
     "28-28 October 2026" for single days), country, and sometimes "Virtual
     Only". Body is free text, sometimes with `Venue:` / `Course fee:` lines.
     Registration is on the organiser's site ("click here").
  B) ISUOG Education (webinars / livestreamed "Live Courses", incl. a Spanish
     pair): tabbed page whose `h1` is just "Overview". Registration section
     has `Date:`/`Time:` lines and, for paid courses, a fee table whose
     columns are timeframes ("Early Bird Discount until <date>" / "Standard
     price from <date>") and rows are member categories, all in GBP. Webinars
     say "free webinar" / "free to attend". CME section states EACCME credits.

The listing date is canonical (a detail page once carried a typo'd year); the
detail only contributes the END date, and only when its start matches.
"""

from __future__ import annotations

import json
import re
import html as html_lib
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .abstract_classifier import extract_abstract_info
from logger import logger


LISTING_URL = "https://www.isuog.org/events/events-calendar.html"
SPECIALTY = "Obstetrics & Gynaecology"  # society remit (same convention as rcog.py)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # Spanish (the two Education courses in Spanish)
    "ene": 1, "abr": 4, "ago": 8, "dic": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_COUNTRY_ALIASES = {"uk": "United Kingdom", "usa": "United States", "us": "United States"}

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}

_CHALLENGE_RE = re.compile(r"just a moment|cf-chl|sgcaptcha|attention required", re.I)


def _clean(s: Optional[str]) -> str:
    s = (s or "").replace("​", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", html_lib.unescape(s)).strip()


def _month_num(name: str) -> Optional[int]:
    n = name.strip().lower().rstrip(".")
    return _MONTHS.get(n) or _MONTHS.get(n[:3])


def _mk_date(d: int, month: str, y: int) -> Optional[date]:
    m = _month_num(month)
    if not m:
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _parse_listing_date(text: str) -> Optional[date]:
    """'Oct 11, 2026' -> date."""
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})", text)
    return _mk_date(int(m.group(2)), m.group(1), int(m.group(3))) if m else None


_RANGE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:de\s+)?([A-Za-zñ]+)?\s*(?:-|–|—|to|and|al|y)\s*"
    r"(?:[A-Za-záéíóú]+day\s+|lunes\s+|martes\s+|s[aá]bado\s+|domingo\s+)?"
    r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:de\s+)?([A-Za-zñ]+)\s*(?:de\s+)?(\d{4})",
    re.I,
)


def clean_venue_line(raw: Optional[str], limit: int = 80) -> Optional[str]:
    """A "Venue:" line is "<City>, <COUNTRY>, <Hospital>, <street>, <room>".
    Keep whole comma-separated parts up to `limit` chars (drops the street/room
    tail), and reject prose (sentences that merely follow the word "Location")."""
    v = _clean(raw or "").rstrip(".")
    if not v:
        return None
    if re.search(r"\.\s+[A-Z]|\b(?:will be|is held|to be held|we welcome)\b|[”\"]", v):
        return None
    out: List[str] = []
    for part in (p.strip() for p in v.split(",")):
        if not part:
            continue
        if out and len(", ".join(out + [part])) > limit:
            break
        out.append(part)
    v = ", ".join(out)[:limit].rstrip(" ,;-")
    return v if len(v) >= 4 else None


def _parse_range(text: str) -> tuple[Optional[date], Optional[date]]:
    """'25-29 January 2027' / '28-28 October 2026' / '30 Jan - 2 Feb 2027' /
    'Saturday 24 October and Sunday 25 October 2026' -> (start, end)."""
    text = _clean(text)
    m = _RANGE_RE.search(text)
    if not m:
        return None, None
    d1, m1, d2, m2, y = m.groups()
    end = _mk_date(int(d2), m2, int(y))
    start = _mk_date(int(d1), m1 or m2, int(y))
    return start, end


def _parse_long_date(text: str) -> Optional[date]:
    """'1st December 2026' / '9 de octubre de 2026' -> date (first match)."""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:de\s+)?([A-Za-zñ]+)\s+(?:de\s+)?(\d{4})", text)
    return _mk_date(int(m.group(1)), m.group(2), int(m.group(3))) if m else None


def _parse_price(cell: str) -> Optional[tuple[float, str]]:
    m = re.search(r"([£$€])\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", cell)
    if not m:
        return None
    return float(m.group(2).replace(",", "")), _CURRENCY_SYMBOLS[m.group(1)]


_ENTRY_JS = r"""() => {
    const clean = s => (s || '').replace(/[​\xa0]/g, ' ').replace(/[ \t]+/g, ' ').trim();
    const entry = document.querySelector('.main-content .entry') || document.querySelector('.entry');
    if (!entry) return null;
    // Education pages put Registration / CME in sibling `.page-section` blocks
    // after the first `.entry`, so read all of them (the sidebar is excluded).
    const roots = [entry].concat(Array.from(document.querySelectorAll('.page-section')));
    const meta = Array.from(document.querySelectorAll('.entry-meta .entry-meta-item'))
        .map(e => clean(e.textContent));
    const intro = entry.querySelector('p.intro');
    const paras = Array.from(entry.querySelectorAll('p'))
        .map(p => clean(p.textContent)).filter(t => t.length > 40);
    let text = '';
    for (const r of roots) {
        const clone = r.cloneNode(true);
        clone.querySelectorAll('.widget-share, .widget-tags, script, style, iframe').forEach(n => n.remove());
        text += '\n' + (clone.innerText || clone.textContent || '');
    }
    const cta = document.querySelector('.main-content .widget-cta a.btn');
    let reg = cta ? cta.href : null;
    if (!reg) {
        for (const a of entry.querySelectorAll('a[href^="http"]')) {
            const ctx = clean((a.textContent || '') + ' ' + (a.parentElement ? a.parentElement.textContent : ''));
            if (/click here|regist/i.test(ctx) && !/isuog\.org/i.test(a.href)) { reg = a.href; break; }
        }
    }
    // Fee tables: only rows owned by the table itself (the site nests a header table in a cell).
    const tables = [];
    for (const r of roots) for (const t of r.querySelectorAll('table')) {
        if (!/[£$€]/.test(t.textContent)) continue;
        if (Array.from(t.querySelectorAll('table')).some(n => /[£$€]/.test(n.textContent))) continue;
        const rows = Array.from(t.querySelectorAll('tr')).filter(x => x.closest('table') === t)
            .map(x => Array.from(x.children).filter(c => /^T[DH]$/.test(c.tagName))
                .map(c => clean(c.innerText || c.textContent)));
        tables.push(rows);
    }
    return {
        meta, intro: intro ? clean(intro.textContent) : null,
        paras: paras.slice(0, 6), text: text.slice(0, 120000), reg, tables,
    };
}"""


class IsuogExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Phase A — listing
    # ------------------------------------------------------------------ #
    def _fetch_listing(self) -> Optional[str]:
        browser = getattr(self, "browser", None)
        for attempt in range(3):
            html = fetch_html(LISTING_URL, browser=browser)
            if html and "tab-upcoming-article-list" in html and not _CHALLENGE_RE.search(html[:2000]):
                return html
            logger.warning(f"ISUOG: listing fetch unusable (attempt {attempt + 1}/3)")
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch_listing()
        if not html:
            logger.warning("ISUOG: listing unavailable — no shells")
            return []

        a = html.index("tab-upcoming-article-list")
        b = html.find('id="tab-past"', a)
        seg = html[a: b if b > 0 else len(html)]

        stated = re.search(r"(\d+)\s+events?\s+found", html[:a][-1500:])
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for blk in re.split(r'<div class="article-block[^"]*"[^>]*>', seg)[1:]:
            t = re.search(r'class="title\s*"><a href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
            if not t:
                continue
            url = html_lib.unescape(t.group(1)).strip()
            title = _clean(re.sub(r"<[^>]+>", "", t.group(2)))
            if not url or not title or url in seen:
                continue
            d = re.search(r'class="date">\s*(.*?)\s*</span>', blk, re.S)
            start = _parse_listing_date(_clean(d.group(1))) if d else None
            if start and start < today:
                continue  # belt and braces: tab is upcoming-only, but never emit the past
            seen.add(url)
            cat = re.search(r'class="category">([^<]*)', blk)
            loc = re.search(r'class="location">\s*([^<]*)', blk)
            shells.append({
                "title": title,
                "booking_url": url,
                "start_date": start.isoformat() if start else None,
                "category": _clean(cat.group(1)) if cat else None,
                "isuog_location": _clean(loc.group(1)) if loc else "",
            })

        if stated and int(stated.group(1)) != len(shells):
            logger.warning(f"ISUOG: site states {stated.group(1)} events, parsed {len(shells)}")
        logger.info(f"ISUOG: {len(shells)} upcoming shells")
        return shells

    # ------------------------------------------------------------------ #
    # Phase B — detail
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        title = _clean(shell.get("title"))
        category = (shell.get("category") or "").strip()
        cat_l = category.lower()
        result: Dict[str, Any] = {"conference_name": title}

        try:
            data = page.evaluate(_ENTRY_JS)
        except Exception as e:
            logger.warning(f"ISUOG: detail evaluate failed for {shell.get('booking_url')}: {e}")
            data = None
        if not data:
            return result

        text: str = data["text"]
        intro: str = data.get("intro") or ""
        meta: List[str] = data.get("meta") or []
        start = date.fromisoformat(shell["start_date"]) if shell.get("start_date") else None

        # ---- event type ------------------------------------------------ #
        if "webinar" in cat_l:
            event_type = "workshop"
        elif "world congress" in cat_l or "partner event" in cat_l:
            event_type = "conference"
        else:
            event_type = "course"
        if event_type == "course" and re.search(r"\b(congress|symposium|conference|meeting)\b", title, re.I) \
                and not re.search(r"\bcourse\b", title, re.I):
            event_type = "conference"
        result["event_type"] = event_type

        # ---- dates ----------------------------------------------------- #
        result.update(self._end_date(start, meta, text))
        start_time = self._start_time(text)
        if start_time:
            result["start_time"] = start_time

        # ---- format / location ---------------------------------------- #
        is_education = cat_l.startswith("education")
        meta_l = " ".join(meta).lower()
        cue = (title + " " + intro).lower()
        if "virtual only" in meta_l or "webinar" in cat_l or re.search(r"livestream|live-stream|online course|virtual course|virtual event", cue):
            fmt = "online"
        elif re.search(r"\bhybrid\b", cue):
            fmt = "hybrid"
        elif is_education:
            fmt = "online"
        else:
            fmt = "in_person"
        result["event_format"] = fmt
        result.update(self._location(shell, meta, text, fmt, is_education))

        # ---- CPD ------------------------------------------------------- #
        cpd = re.search(r"with\s+([0-9]+(?:\.[0-9]+)?)(?:\s+[0-9]+(?:\.[0-9]+)?)?\s+European CME credits", text, re.I)
        result["cpd_points"] = float(cpd.group(1)) if cpd else None
        result["cpd_accredited"] = bool(re.search(r"has been accredited by", text, re.I))

        # ---- pricing --------------------------------------------------- #
        result["pricing_tiers"] = self._pricing(data.get("tables") or [], text, intro, cat_l)
        result["is_sold_out"] = bool(re.search(r"sold out|fully booked|registration (?:is )?closed", text, re.I))

        if data.get("reg"):
            result["booking_url"] = data["reg"]

        # ---- abstracts (deterministic; almost always none) ------------- #
        try:
            is_open, deadline = extract_abstract_info(text)
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None
        except Exception:
            pass

        # ---- soft fields ---------------------------------------------- #
        result["specialty"] = SPECIALTY
        result["description"] = self._description(title, data, llm_call)
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _end_date(start: Optional[date], meta: List[str], text: str) -> Dict[str, Any]:
        """End date only if the detail agrees with the listing start (the
        listing is canonical; detail pages carry typos like a wrong year)."""
        if not start:
            return {}
        candidates: List[tuple] = []
        # approved courses: entry-meta date range
        for m in meta[:1]:
            candidates.append(_parse_range(m))
        # education: CME header "24/10/2026 - 25/10/2026"
        cme = re.search(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})", text)
        if cme:
            try:
                candidates.append((date(int(cme.group(3)), int(cme.group(2)), int(cme.group(1))),
                                   date(int(cme.group(6)), int(cme.group(5)), int(cme.group(4)))))
            except ValueError:
                pass
        # education: "Date: Saturday 24 October and Sunday 25 October 2026"
        dl = re.search(r"\b(?:Date|Fecha)\s*:\s*([^\n]+)", text)
        if dl:
            candidates.append(_parse_range(dl.group(1)))
        for s, e in candidates:
            if s == start and e and start <= e <= start + timedelta(days=14):
                return {"end_date": e.isoformat()}
        return {}

    @staticmethod
    def _start_time(text: str) -> Optional[str]:
        m = re.search(r"\b(?:Time|Hora)\s*:[^\n]{0,60}?(\d{1,2}):(\d{2})", text)
        if not m:
            m = re.search(r"\bDate\s*&\s*Time\s*:[^\n]*?(\d{1,2}):(\d{2})", text)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2))
        return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None

    @staticmethod
    def _location(shell, meta, text, fmt, is_education) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        listing_loc = _clean(shell.get("isuog_location"))
        city = country = None
        if listing_loc:
            parts = [p.strip() for p in listing_loc.split(",") if p.strip()]
            if len(parts) >= 2:
                city, country = parts[0], parts[-1]
            elif parts:
                country = parts[0]
        if not country and len(meta) > 1 and meta[1] and not re.search(r"virtual only", meta[1], re.I):
            country = meta[1]

        venue = None
        vm = re.search(r"\b(?:Venue|Location)\s*:\s*([^\n]{4,})", text)
        if vm:
            venue = clean_venue_line(vm.group(1))

        if fmt == "online":
            # ISUOG's listing tags its (London-run) Education items with "UK";
            # that is the organiser, not an event location.
            if is_education:
                return {"venue_name": None, "city": None, "region": None}
            return {"venue_name": venue, "city": None,
                    "region": _COUNTRY_ALIASES.get((country or "").lower(), country)}

        if venue and not city:
            vparts = [p.strip() for p in venue.split(",") if p.strip()]
            if len(vparts) >= 2 and country and vparts[1].lower() == country.lower():
                city = vparts[0]  # "Malmö, SWEDEN, Skane University Hospital, ..."
        elif venue and city:
            # keep the venue's accented spelling when it is the same city ("Malmö" vs "Malmo")
            import unicodedata
            fold = lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
            v0 = venue.split(",")[0].strip()
            if fold(v0) == fold(city):
                city = v0
        out["venue_name"] = venue
        out["city"] = city
        out["region"] = _COUNTRY_ALIASES.get((country or "").lower(), country)
        return out

    @staticmethod
    def _pricing(tables: List[List[List[str]]], text: str, intro: str, cat_l: str) -> List[Dict[str, Any]]:
        today = date.today()
        tiers: List[Dict[str, Any]] = []
        for rows in tables:
            rows = [r for r in rows if r]
            if len(rows) < 2:
                continue
            header = rows[0]
            cols: List[Optional[Dict[str, Any]]] = [None]  # column 0 = category
            for h in header[1:]:
                hl = h.lower()
                early = bool(re.search(r"early|anticipad", hl))
                until = _parse_long_date(h) if early else None
                if early and until and until < today:
                    cols.append(None)  # expired early-bird column
                    continue
                cols.append({"label": "Early Bird" if early else "Standard",
                             "early": early, "deadline": until})
            if len(cols) == 1:
                continue
            for r in rows[1:]:
                category = _clean(re.sub(r"\*+", "", r[0])).strip(" -–")
                for i, c in enumerate(cols):
                    if i == 0 or c is None or i >= len(r):
                        continue
                    p = _parse_price(r[i])
                    if not p or not category:
                        continue
                    tiers.append({
                        "tier_label": f"Registration · {category} · {c['label']}",
                        "price_gbp": p[0],
                        "currency": p[1],
                        "is_early_bird": c["early"],
                        "early_bird_deadline": c["deadline"].isoformat() if c["deadline"] else None,
                    })
        if tiers:
            return tiers
        # Approved courses sometimes state one fee in prose: "Course fee: 17500 SEK plus
        # 25% VAT, total 21875 SEK". Prefer the stated total.
        fm = re.search(r"\b(?:course|registration)\s+fees?\s*:\s*([^\n]{3,200})", text, re.I)
        if fm:
            line = fm.group(1)
            code = r"(GBP|USD|EUR|SEK|DKK|NOK|CHF|CAD|AUD|INR|JPY|CNY|HKD|SGD|BRL)"
            num = r"([0-9][0-9,. ]*[0-9]|[0-9])"
            amt = cur = None
            # "total 21875 SEK" / "total: SEK 21875" first, then the first "<n> <CUR>" / "<CUR> <n>"
            for pat in (r"total\s*:?\s*" + num + r"\s*" + code,
                        r"total\s*:?\s*" + code + r"\s*" + num,
                        num + r"\s*" + code,
                        code + r"\s*" + num):
                mm = re.search(pat, line, re.I)
                if mm:
                    g = mm.groups()
                    amt, cur = (g[0], g[1]) if re.match(r"[0-9]", g[0]) else (g[1], g[0])
                    break
            if not amt:
                sym = _parse_price(line)
                if sym:
                    amt, cur = str(sym[0]), {v: k for k, v in _CURRENCY_SYMBOLS.items()}[sym[1]]
                    cur = sym[1]
            if amt and cur:
                try:
                    price = float(re.sub(r"[ ,]", "", amt))
                except ValueError:
                    price = None
                if price is not None:
                    return [{"tier_label": "Registration · Course fee · Standard", "price_gbp": price,
                             "currency": cur.upper(), "is_early_bird": False, "early_bird_deadline": None}]
        if "webinar" in cat_l and re.search(r"\bfree\b(?:\s+[\w-]+){0,3}\s+webinar|free to attend", text, re.I):
            return [{"tier_label": "Registration · Webinar · Free", "price_gbp": 0.0,
                     "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None}]
        return []

    @staticmethod
    def _description(title: str, data: Dict[str, Any], llm_call) -> Optional[str]:
        paras: List[str] = data.get("paras") or []
        intro = data.get("intro")
        backstop = None
        for p in ([intro] if intro else []) + paras:
            if p and len(p) > 40 and not p.lower().startswith(("register", "email", "contact")):
                backstop = p[:400].rsplit(" ", 1)[0] if len(p) > 400 else p
                break

        body = " ".join(([intro] if intro else []) + paras)[:3000]
        if body:
            prompt = (
                "Summarise this medical ultrasound event in 30-50 words using ONLY the text below. "
                "Do not invent dates, prices or places. Do not include email addresses or phone numbers.\n\n"
                f"TITLE: {title}\n\nTEXT:\n{body}\n\n"
                'Respond with valid JSON only: {"description": "..." or null}'
            )
            try:
                raw = llm_call(prompt)
            except Exception:
                raw = None
            if raw:
                m = re.search(r"\{.*\}", raw, re.S)
                if m:
                    try:
                        d = json.loads(m.group(0)).get("description")
                        if isinstance(d, str) and len(d.strip()) > 20:
                            return d.strip()
                    except Exception:
                        pass
        return backstop
