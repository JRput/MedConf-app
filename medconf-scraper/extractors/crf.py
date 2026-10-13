"""CRF (Cardiovascular Research Foundation) events calendar: family subclass with a flat-page listing.

`/crf/news-and-events/events-calendar` is ONE server-rendered page of `<div class="box">` cards (inside
`section.upc-events`): `<h3>` title (with <sup>(R)</sup>), `p.subhead` tagline, then a paragraph
"October 31-November 3, 2026<br/>Venue<br/>City, ST" (the venue may be one line "Fontainebleau Miami Beach, Miami Beach, FL"
or two "Jacob K. Javits<br/>Convention Center, North<br/>New York, NY"), and an external CTA link (REGISTER / SAVE THE DATE)
to the meeting's own site. Cards run ~5 years out; only those within MAX_FUTURE_DAYS are kept, and the fundraising Gala
is not an educational event.

Because the cards carry every hard field, shells are complete. The registration page of a meeting (booking_url) is
read for fees where it publishes a rate grid: `<div>` grids (not `<table>`s) of "Registration Rates for TCT 2026" with
columns EARLY-BIRD / STANDARD / LATE / ONE-DAY ACCESS and rows Physician / Allied Health Professional / Industry /
Fellow (Free) / U.S. Government, all in USD. Meetings without a link yet use `<listing>#<slug>` as their URL.
"""
import html as _html
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive, pick_event_dates, _meta
from logger import logger

_BOX_RE = re.compile(r'(?is)<div class="box">(.*?)(?=<div class="box">|</section>)')
_US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
_PRICE_RE = re.compile(r"^(?:US)?\$\s?(\d[\d,]*(?:\.\d\d)?)$")
_SKIP_ROW_RE = re.compile(r"(?i)application|apply|^ends\b|closed|^\*|see |^choose|^through|^starts|\bto\b.*\d|^all figures")
_COL_RE = re.compile(r"(?i)^(early[\s-]?bird|standard|late|one[\s-]day access)\s*[*†]*$")
_DESC_RE = re.compile(r"(?i)^(?:through|starts|starting|to\b|\d{1,2}:\d{2}\s*[ap]m|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d)")


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


class CrfExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.crf.org/crf/news-and-events/events-calendar"
    SOCIETY = "CRF"
    DEFAULT_SPECIALTY = "Cardiology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "USD"
    MAX_FUTURE_DAYS = 550

    # ---- listing -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(self.LISTING_URL)
        if not html or 'class="upc-events"' not in html:
            return None
        sect = html[html.index('class="upc-events"'):]
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for bm in _BOX_RE.finditer(sect):
            box = bm.group(1)
            hm = re.search(r"(?is)<h3\b[^>]*>(.*?)</h3>", box)
            if not hm:
                continue
            title = re.sub(r"\s*®|™", "", _text(re.sub(r"(?is)<sup>.*?</sup>", "", hm.group(1)))).strip()
            if not title or re.search(r"(?i)\bgala\b", title):
                continue
            sub = re.search(r"(?is)<p class=.subhead.>(.*?)</p>", box)
            sub = re.sub(r"\s*®|™", "", _text(re.sub(r"(?is)<sup>.*?</sup>", "", sub.group(1)))).strip() if sub else None
            pm = re.search(r'(?is)<div style="flex: 1 1 65%">\s*<p>(.*?)</p>', box)
            lines = [x for x in (_text(p) for p in re.split(r"(?i)<br\s*/?>", pm.group(1))) if x] if pm else []
            if not lines:
                continue
            d = pick_event_dates(lines[0].replace("–", "-"), today)
            if not d or d[1] < today.isoformat() or (date.fromisoformat(d[0]) - today).days > self.MAX_FUTURE_DAYS:
                continue
            venue, city, region = self._place(lines[1:])
            link = None
            for hm2 in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>\s*([^<]*)""", box):
                if "addevent.com" not in hm2.group(1) and "crf.org" not in hm2.group(1):
                    link = _html.unescape(hm2.group(1))
                    break
            slug = re.sub(r"[^a-z0-9]+", "-", f"{title} {d[0][:4]}".lower()).strip("-")
            url = link or f"{self.LISTING_URL}#{slug}"
            if url in seen:
                url = f"{self.LISTING_URL}#{slug}"
            seen.add(url)
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": d[0], "end_date": d[1],
                           "venue_raw": ", ".join(lines[1:]) or None, "category": "course" if re.search(r"(?i)\bcourse\b", title) else "conference",
                           "_tagline": sub, "_venue": venue, "_city": city, "_region": region,
                           "_has_link": bool(link)})
        logger.info(f"{self.SOCIETY}: {len(shells)} upcoming events on the calendar page")
        return shells or None

    @staticmethod
    def _place(lines: List[str]):
        """['San Diego Convention Center', 'San Diego, CA'] / ['Venue, City, FL'] -> (venue, city, region)."""
        if not lines:
            return None, None, None
        last = [p.strip() for p in lines[-1].split(",") if p.strip()]
        venue_lines = lines[:-1]
        if len(lines) == 1 and len(last) >= 3:                       # "Fontainebleau Miami Beach, Miami Beach, FL"
            venue_lines, last = [", ".join(last[:-2])], last[-2:]
        city = last[0] if last else None
        tail = last[1] if len(last) > 1 else None
        region = ("United States" if tail in _US_STATES else tail) if tail else None
        if tail in ("D.C.",):
            region = "United States"
        venue = ", ".join(venue_lines) or None
        if venue and len(venue_lines) == 2 and re.match(r"(?i)^(?:convention|conference)\b", venue_lines[1]):
            venue = " ".join(venue_lines).replace(" ,", ",")           # "Jacob K. Javits Convention Center, North"
        return venue, city, region

    # ---- detail ------------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = ""
        if shell.get("_has_link") and page is not None:
            try:
                html = page.content()
            except Exception:  # noqa: BLE001
                html = ""
        return self.detail_from_html(html, shell, llm_call)

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        title = shell["title"]
        out: Dict[str, Any] = {
            "conference_name": title, "society": self.SOCIETY, "event_type": shell.get("category") or "conference",
            "start_date": shell["start_date"], "end_date": shell["end_date"], "specialty": self.DEFAULT_SPECIALTY,
            "event_format": "in_person",
        }
        for k_out, k_sh in (("venue_name", "_venue"), ("city", "_city"), ("region", "_region")):
            if shell.get(k_sh):
                out[k_out] = shell[k_sh]
        desc = None
        if html:
            md = _meta(html, "og:description") or _meta(html, "description")
            md = re.sub(r"\s+", " ", _html.unescape(md or "")).strip()
            if len(md) >= 60 and not re.search(r"(?i)cookie|javascript|just a moment", md):
                desc = md[:600]
        if not desc and shell.get("_tagline"):
            desc = f"{title}: {shell['_tagline'].rstrip('. ')}. Organised by the Cardiovascular Research Foundation (CRF)."
        if desc:
            out["description"] = desc
        if html:
            tiers = self.grid_fees(html)
            if tiers:
                out["pricing_tiers"] = tiers
            lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|template)\b.*?</\1\s*>", " ", html))
            text = " ".join(lines)
            m = re.search(r"(?i)(?:up to|maximum of)\s+(\d+(?:\.\d+)?)\s+(?:AMA PRA Category 1 )?(?:CME )?credits?", text)
            if m:
                out["cpd_points"], out["cpd_accredited"] = float(m.group(1)), True
        if not out.get("pricing_tiers") and shell.get("_has_link"):
            out["organiser_url"] = shell["booking_url"]               # rate grid not in the HTML: let the explorer follow it
        return out

    @staticmethod
    def grid_fees(html: str) -> List[Dict[str, Any]]:
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|template)\b.*?</\1\s*>", " ", html)))
        start = next((i for i, l in enumerate(lines) if re.match(r"(?i)^registration rates for\b", l)), None)
        if start is None:
            return []
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"(?i)^(?:exhibitor rates|all figures are in)", lines[i])), len(lines))
        block = lines[start + 1:end]
        cols: List[str] = []
        section = None
        i = 0
        while i < len(block):                                       # header: [section] then the column names
            l = block[i]
            if _COL_RE.match(l):
                cols.append(re.sub(r"[*†]+$", "", _COL_RE.match(l).group(1)).strip())
                i += 1
                while i < len(block) and not _COL_RE.match(block[i]) and (_DESC_RE.match(block[i]) or _SKIP_ROW_RE.search(block[i])):
                    i += 1                                          # "Through June 3" / "1:59 PM" / "to Sept. 2, 1:59 PM" sub-lines
                continue
            if cols:
                break
            if not re.match(r"(?i)^choose your pass", l):
                section = l
            i += 1
        if not cols:
            return []
        rows: List[tuple] = []
        label, vals = None, []
        for l in block[i:]:
            pm = _PRICE_RE.match(l.replace(",", "", 0))
            if pm or re.match(r"(?i)^(?:free|n/?a)$", l):
                vals.append(0.0 if l.lower() == "free" else (float(pm.group(1).replace(",", "")) if pm else None))
            elif _SKIP_ROW_RE.search(l) or _DESC_RE.match(l):
                continue
            elif label and not vals:
                label = f"{label} {l}".strip()                      # label wrapped over two lines
            else:
                if label and vals:
                    rows.append((label, vals))
                label, vals = l, []
        if label and vals:
            rows.append((label, vals))
        tiers = []
        for label, vals in rows:
            label = re.sub(r"\s*[*†‡]+$", "", label).strip()
            if len(vals) == 1 and vals[0] == 0.0 and len(cols) > 1:
                vals = vals * len(cols)                              # one "Free" spanning every column (fellows / students)
            if len(vals) != len(cols):
                continue
            for col, v in zip(cols, vals):
                if v is None:
                    continue
                early = bool(re.match(r"(?i)early", col))
                tf = "Early bird" if early else col.title()
                tiers.append({"tier_label": " · ".join(x for x in (section, label, tf) if x), "price_gbp": v, "currency": "USD",
                              "is_early_bird": early, "early_bird_deadline": None})
        return tiers
