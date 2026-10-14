"""ARRS (American Roentgen Ray Society): events table + Annual Meetings, family subclass with a hand-built listing.

`upcoming_events.aspx` is a server-rendered ASP.NET page with one `<table class="arrs-evt-table">`; every row is
`tr.type-symposium | type-longitudinal | type-ajr | type-annual` with an event cell, a date cell and a location cell
holding the "Learn more" link. Near-term dates are year-less ("October 15"); Annual Meetings carry a range with the
year ("May 2-5, 2027"). Longitudinal-course rows are SESSIONS of two courses (rows sharing one link), so each course is
one parent row with `sessions`. Course and symposium pages list fees as "label" / "$695" line pairs ("FREE" for
trainees); the Annual Meeting site and the AJR Live webinar pages publish no fee yet.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .pricing_tables import parse_pricing_tables
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive, _iso, _mon

# 2026-10-14: rows gained a data-end="YYYY-MM-DD" attribute (<tr class="type-ajr" data-end="2026-10-14">)
_ROW_RE = re.compile(r'(?is)<tr class="type-(\w+)"[^>]*>(.*?)</tr>')
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_YEARLESS_RE = re.compile(rf"^({_MONTH})\.?\s+(\d{{1,2}})$")
_RANGE_RE = re.compile(rf"^({_MONTH})\.?\s+(\d{{1,2}})\s*[–-]\s*(?:({_MONTH})\.?\s+)?(\d{{1,2}}),\s*(\d{{4}})$")
_TXT = lambda s: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()   # noqa: E731


def _cell(row: str, cls: str) -> str:
    m = re.search(rf'(?is)<td[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</td>', row)
    return m.group(1) if m else ""


class ArrsExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.arrs.org/ARRSLIVE/ARRSLIVE/Education/upcoming_events.aspx"
    SOCIETY = "ARRS"
    DEFAULT_SPECIALTY = "Radiology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "USD"

    # ---- listing -----------------------------------------------------------
    @staticmethod
    def _dates(label: str, today: date):
        label = label.strip()
        m = _RANGE_RE.match(label)
        if m:
            m1, d1, m2, d2, yr = m.groups()
            return _iso(int(yr), _mon(m1), int(d1)), _iso(int(yr), _mon(m2 or m1), int(d2))
        m = _YEARLESS_RE.match(label)
        if m:
            d = _iso(today.year, _mon(m.group(1)), int(m.group(2)))
            if d and date.fromisoformat(d) < today - timedelta(days=90):     # Jan/Feb rows listed in the autumn belong to next year
                d = _iso(today.year + 1, _mon(m.group(1)), int(m.group(2)))
            return d, d
        return None, None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        html = self._fetch(self.LISTING_URL)
        if not html:
            return None
        shells: List[Dict[str, Any]] = []
        courses: Dict[str, Dict[str, Any]] = {}
        for kind, row in _ROW_RE.findall(html):
            name_html = _cell(row, "arrs-evt-name")
            s, e = self._dates(_TXT(_cell(row, "arrs-evt-date")), today)
            href = (re.search(r'href="([^"]+)"', row) or [None, None])[1]
            if not s or e < today.isoformat():
                continue
            loc_html = _cell(row, "arrs-evt-location")
            if kind == "longitudinal":
                if not href:
                    continue
                topics = [_TXT(t) for t in re.findall(r"(?is)<span class=\"arrs-presentation\"[^>]*>(.*?)</span>", name_html)]
                badge = _TXT((re.search(r'(?is)arrs-course-badge[^>]*>(.*?)</span>', name_html) or [None, ""])[1])
                c = courses.setdefault(href, {"title": badge, "booking_url": href, "source_url": href, "sessions": []})
                c["sessions"].append({"_idx": len(c["sessions"]), "start_date": s, "end_date": None, "start_time": None, "duration_text": None,
                                      "availability_status": "unknown", "spots_left": None, "booking_url": href, "venue_name": None, "city": None,
                                      "region": None, "notes": "; ".join(topics) or None})
                continue
            name = _TXT(re.sub(r"(?is)<br\s*/?>", "|", name_html))
            title = re.sub(r"^(?:Virtual Symposium|AJR Live Webinar):\s*\|?\s*", "", name).replace("|", " ").strip()
            if kind == "annual":
                hotel = _TXT((re.search(r'(?is)arrs-evt-hotel">(.*?)</span>', loc_html) or [None, ""])[1])
                city = _TXT(re.sub(r"(?is)<span.*?</span>|<div.*?</div>", " ", loc_html))
                slug = re.sub(r"\W+", "-", title.lower())
                url = href or f"{self.LISTING_URL}#{slug}"
                shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": s, "end_date": e, "start_time": None,
                               "venue_raw": f"{hotel}, {city}" if hotel else city, "category": "Annual Meeting"})
            else:
                if not href:
                    continue
                shells.append({"title": title, "booking_url": href, "source_url": href, "start_date": s, "end_date": e, "start_time": None,
                               "venue_raw": "Online", "category": "Virtual Symposium" if kind == "symposium" else "AJR Live Webinar"})
        for href, c in courses.items():          # real course names live on the course page (<h1>)
            time.sleep(self.REQUEST_GAP_S)
            ph = self._fetch(href) or ""
            h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", ph)
            c["title"] = _TXT(h1.group(1)) if h1 else c["title"]
            c["sessions"].sort(key=lambda x: x["start_date"])
            for i, ss in enumerate(c["sessions"]):
                ss["_idx"] = i
            c.update({"start_date": c["sessions"][0]["start_date"], "end_date": c["sessions"][0]["start_date"], "start_time": None,
                      "venue_raw": "Online", "category": "Longitudinal Course"})
            shells.append(c)
        shells.sort(key=lambda x: x["start_date"])
        logger.info(f"ARRS listing: {len(shells)} shells")
        return shells or None

    # ---- detail ------------------------------------------------------------
    @staticmethod
    def _tiers(lines: List[str]) -> List[Dict[str, Any]]:
        tiers, seen = [], set()
        for i in range(1, len(lines)):
            pm = re.match(r"^(?:\$\s?(\d[\d,]*(?:\.\d\d)?)|(FREE))$", lines[i], re.I)
            lab = lines[i - 1]
            if not pm or not re.match(r"^[A-Za-z][A-Za-z \-/&]{2,40}$", lab) or re.match(r"(?i)^(register|price|fee)", lab):
                continue
            if lab in seen:
                continue
            seen.add(lab)
            tiers.append({"tier_label": f"Registration · {lab}", "price_gbp": 0.0 if pm.group(2) else float(pm.group(1).replace(",", "")),
                          "currency": "USD", "is_early_bird": False, "early_bird_deadline": None})
        return tiers

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        cat = shell.get("category")
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html or "")))
        text = " ".join(lines)
        out: Dict[str, Any] = {"society": self.SOCIETY, "specialty": "Radiology", "start_date": shell["start_date"], "end_date": shell["end_date"],
                               "event_type": "conference" if cat == "Annual Meeting" else ("course" if cat == "Longitudinal Course" else "workshop")}
        h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html or "")
        title = _TXT(h1.group(1)) if h1 else ""
        i = next((k for k, l in enumerate(lines) if title and l == title), None)
        if i is None and cat == "AJR Live Webinar":
            i = next((k for k in range(len(lines) - 1, -1, -1) if lines[k] == shell["title"]), None)
        if cat == "Annual Meeting":
            tm_ = re.search(r"(?is)<title>(.*?)</title>", html or "")
            tt = _TXT(tm_.group(1)) if tm_ else ""
            if "#" not in shell["booking_url"] and " \u2013 " in tt:
                out["description"] = tt.split(" \u2013 ", 1)[1][:600]          # "ARRS 2027 | May 2-5, 2027 \u2013 The premier educational event..."
        else:
            for pm_ in (re.finditer(r"(?is)<p[^>]*>(.*?)</p>", (html or "")[h1.end():h1.end() + 20000]) if h1 else []):
                para = _TXT(pm_.group(1))
                if len(para) >= 80 and not re.search(r"(?i)cookies|^date\b|course director|^register", para[:60]):
                    out["description"] = para[:600]
                    break
            if "description" not in out:
                d = next((l for l in lines[(i or 0) + 1:(i or 0) + 14] if len(l) >= 120 and not re.search(r"(?i)cookies|system upgrade|maintenance|currently experiencing|incident", l)), None) if i is not None else None
                if d:
                    out["description"] = d[:600]
        if shell.get("venue_raw") == "Online":
            out["event_format"] = "online"
        elif cat == "Annual Meeting":
            parts = [p.strip() for p in (shell.get("venue_raw") or "").split(",") if p.strip()]
            if len(parts) >= 3:
                out["venue_name"], out["city"], out["region"] = parts[0], parts[1], "United States"
            elif len(parts) == 2:
                out["city"], out["region"] = parts[0], "United States"
            out["event_format"] = "hybrid" if re.search(r"(?i)\bor online\b|\blivestream\b", text) else "in_person"
        tm = re.search(r"(?:Date & Time:|@|When)[^|]{0,40}?(\d{1,2}):(\d\d)\s*(am|pm)", text, re.I)
        if tm:
            hh = int(tm.group(1)) % 12 + (12 if tm.group(3).lower() == "pm" else 0)
            out["start_time"] = f"{hh:02d}:{tm.group(2)}"
        cm = re.search(r"(\d+(?:\.\d+)?)\s*CME Credits?", text, re.I)
        if cm:
            out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
        if cat in ("Virtual Symposium", "Longitudinal Course"):
            tiers = parse_pricing_tables(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html or ""), default_currency="USD")
            if not tiers:
                tiers = self._tiers(lines[i:] if i is not None else lines)
            if tiers:
                out["pricing_tiers"] = tiers
        if cat == "Longitudinal Course":
            out["sessions"] = shell["sessions"]
            out["event_format"] = "online"
        return out
