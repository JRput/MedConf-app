"""ESAIC (European Society of Anaesthesiology and Intensive Care) events: WordPress family subclass, WP REST listing.

`esaic.org/events/` is a JS-rendered calendar, but the page's data is the public custom post type
`/wp-json/wp/v2/event` whose ACF block carries `start_date` / `end_date` (YYYYMMDD), `place`, `city`,
`external_url` and a `cta` register link. Phase A reads that API (browser first, then httpx fallback);
nothing is scraped from the rendered calendar.

The ~24 records are a mix, told apart by the `event_type-*` class on each record:
- congress / course / masterclass: ESAIC's own events, with their own page (fees table, venue, EACCME credits)
  which the family detail parser reads. Euroanaesthesia 20xx pages redirect to euroanaesthesia.org/<year>/.
- endorsed / external: other organisers' meetings. Their esaic.org URL redirects straight to the organiser, so
  the detail comes from the API record only (dates, place); `booking_url` in the detail is the organiser site.
- webinar (hosted on academy.esaic.org, a JS learning platform) and exam (EDAIC Part II sittings) are skipped.
EUR is the default currency; ESAIC fee tables are in euro.
"""
import html as _html
import json
import re
import time
from datetime import date
from urllib.parse import urljoin, urlparse
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, classify_event_type, find_dates, split_location

_API = "https://esaic.org/wp-json/wp/v2/event?per_page=100&_fields=link,title,acf,class_list"
_SKIP_KINDS = {"webinar", "exam"}
_EXTERNAL_KINDS = {"endorsed", "external"}


def _iso(v: Any) -> Optional[str]:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", str(v or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _kind(rec: Dict[str, Any]) -> str:
    for c in rec.get("class_list") or []:
        if c.startswith("event_type-"):
            return c[len("event_type-"):]
    return ""


class EsaicExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://esaic.org/events/"
    SOCIETY = "ESAIC"
    DEFAULT_SPECIALTY = "Anaesthetics"
    DEFAULT_CURRENCY = "EUR"
    PREFER_DEFAULT_SPECIALTY = True        # every ESAIC event is anaesthesia / intensive care; the title classifier mislabels them

    def _api_records(self) -> List[Dict[str, Any]]:
        browser = getattr(self, "browser", None)
        for attempt in range(3):
            body = None
            if browser is not None:
                try:
                    browser.navigate(_API)
                    body = browser.page.inner_text("body")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"ESAIC API browser load {attempt + 1}/3 failed: {e}")
            if not body or not body.lstrip().startswith("["):
                body = fetch_html(_API, browser=browser, headers={"Accept": "application/json"})
            try:
                recs = json.loads(body or "[]")
                if isinstance(recs, list) and recs:
                    return [r for r in recs if isinstance(r, dict)]
            except ValueError:
                pass
            time.sleep(2 * (attempt + 1))
        return []

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for rec in self._api_records():
            acf = rec.get("acf") if isinstance(rec.get("acf"), dict) else {}
            kind = _kind(rec)
            title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", (rec.get("title") or {}).get("rendered", "")))).strip()
            url = rec.get("link") or ""
            start, end = _iso(acf.get("start_date")), _iso(acf.get("end_date"))
            if not (title and url and start) or kind in _SKIP_KINDS or url in seen:
                continue
            end = end if end and end >= start else start
            if end < today or (date.fromisoformat(start) - date.today()).days > self.MAX_FUTURE_DAYS:
                continue
            seen.add(url)
            place = re.sub(r"\s*[\r\n]+\s*", ", ", str(acf.get("place") or "")).strip(" ,")
            city = str(acf.get("city") or "").strip()
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": start, "end_date": end,
                           "start_time": None, "venue_raw": place or city or None, "category": kind or None,
                           "esaic_kind": kind, "external_url": (acf.get("external_url") or "").strip() or None})
        logger.info(f"ESAIC WP REST: {len(shells)} upcoming shells")
        return shells or None

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        landed = ""
        try:
            landed = (page.url or "") if page is not None else ""
        except Exception:  # noqa: BLE001
            landed = ""
        off_site = bool(landed) and not re.match(r"https?://(?:www\.)?esaic\.org/events/", landed)
        if (shell.get("esaic_kind") or "") in _EXTERNAL_KINDS or off_site:
            return self._listing_only(shell, page if off_site else None)
        html = page.content() if page is not None else ""
        out = self.detail_from_html(html, shell, llm_call)
        out["start_date"], out["end_date"] = shell["start_date"], shell["end_date"]   # the API's ACF dates win over page prose
        main = re.search(r"(?is)<main\b.*?</main>", html)
        lines = html_to_lines(main.group(0) if main else html)
        tiers = self._fee_rows(lines)
        if tiers:
            out["pricing_tiers"] = tiers
        desc = self._event_details(lines)
        if desc:
            out["description"] = desc
        if not out.get("venue_name"):
            for i, ln in enumerate(lines):
                if re.search(r"will take place at\s*:?\s*$", ln, re.I) and i + 1 < len(lines):
                    out["venue_name"] = lines[i + 1].strip()[:120]
                    break
        return out

    def _fee_rows(self, lines: List[str]) -> List[Dict[str, Any]]:
        """'Registration Fee' block: a label line followed by a '\u20ac 595' line, one pair per membership type."""
        start = next((i for i, l in enumerate(lines) if re.match(r"^registration fee\b", l, re.I)), None)
        if start is None:
            return []
        tiers: List[Dict[str, Any]] = []
        for i in range(start + 1, min(start + 40, len(lines))):
            m = re.match(r"^\u20ac\s*([\d.,]+)\s*$", lines[i])
            if not m:
                if tiers and re.match(r"^(?:acknowledg|programme|other events|see all)", lines[i], re.I):
                    break
                continue
            label = re.sub(r"[*\s]+$", "", lines[i - 1]).strip()
            if not label or label.startswith("\u20ac"):
                continue
            try:
                amount = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            tiers.append({"tier_label": f"Registration Fee \u00b7 {label}", "price_gbp": amount, "currency": "EUR",
                          "is_early_bird": False, "early_bird_deadline": None})
        return tiers

    @staticmethod
    def _page_description(page) -> Optional[str]:
        """Meta description of the organiser page the esaic.org URL redirected to, if it is real prose."""
        if page is None:
            return None
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            return None
        for name in ("og:description", "description"):
            m = re.search(r'(?is)<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']{60,})["\']' % re.escape(name), html)
            if m:
                d = re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip()
                if not re.search(r"cookie|technical storage|consent|javascript", d, re.I):
                    return d[:600]
        return None

    @staticmethod
    def _event_details(lines: List[str]) -> Optional[str]:
        """First real paragraph under the 'Event Details' heading (the meta description is a generic template)."""
        for i, ln in enumerate(lines):
            if re.match(r"^event details$", ln, re.I):
                para = " ".join(l for l in lines[i + 1:i + 8] if len(l) > 3)
                para = re.sub(r"\s+", " ", para).strip()
                return para[:600] if len(para) >= 40 else None
        return None

    def _listing_only(self, shell: Dict[str, Any], page=None) -> Dict[str, Any]:
        """Endorsed / external meeting: the API record is the source of truth; the organiser site is not parsed."""
        title = shell["title"]
        out: Dict[str, Any] = {"society": self.SOCIETY, "start_date": shell["start_date"], "end_date": shell["end_date"],
                               "event_type": classify_event_type(title, ""), "pricing_tiers": []}
        raw = (shell.get("venue_raw") or "").strip()
        v, c, k = split_location(raw)
        if not (v or c) and raw:                                    # "Istanbul, Turkey" / "Porto, Portugal"
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            c = parts[0] if parts else None
            k = parts[-1] if len(parts) > 1 else k
        if v:
            out["venue_name"] = v
        if c:
            out["city"] = c
        if k:
            out["region"] = k
        if v or c:
            out["event_format"] = "in_person"
        out["specialty"] = self.DEFAULT_SPECIALTY
        desc = self._page_description(page)
        who = "an anaesthesiology and intensive care meeting listed in the ESAIC events calendar" if (shell.get("esaic_kind") or "") in _EXTERNAL_KINDS \
            else "an ESAIC congress"
        out["description"] = desc or f"{title}: {who}. The event website has the programme and registration."
        if shell.get("external_url"):
            out["booking_url"] = shell["external_url"]               # register with the organiser, not on esaic.org
        # fee grids are read only for ESAIC's own congresses (Euroanaesthesia, Connect). Third-party sites are too varied:
        # a trial parse of one endorsed congress turned its "includes" bullets into tiers. The remediator follows those sites.
        tiers = self._organiser_fees(page) if (shell.get("esaic_kind") or "") == "congress" else []
        if tiers:
            out["pricing_tiers"] = tiers
        return out

    def _organiser_fees(self, page) -> List[Dict[str, Any]]:
        """Fee grid on the organiser site the esaic.org URL redirected to: the landed page itself, else ONE same-site
        'Registration' page (Euroanaesthesia publishes its grid at /<year>/registration/). Structured tables only."""
        if page is None:
            return []
        try:
            html, base = page.content(), page.url
        except Exception:  # noqa: BLE001
            return []
        pages = [html]
        host = urlparse(base).netloc.lower().removeprefix("www.")
        links = []
        for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html):
            href, label = urljoin(base, _html.unescape(m.group(1))), re.sub(r"<[^>]+>", " ", m.group(2))
            if urlparse(href).netloc.lower().removeprefix("www.") != host or href.rstrip("/") == base.rstrip("/"):
                continue
            if re.search(r"registration|register|fees", href, re.I) or re.search(r"^\s*(?:registration|register(?: now)?|fees)\s*$", label, re.I):
                if not re.search(r"\.(?:pdf|docx?|xlsx?)(?:$|\?)", href, re.I) and href not in links:
                    links.append(href)
        for href in links[:1]:
            time.sleep(self.REQUEST_GAP_S)
            body = fetch_html(href, browser=getattr(self, "browser", None))
            if body:
                pages.append(body)
        for body in pages:
            try:
                tiers = parse_pricing_tables(body, default_currency=self.DEFAULT_CURRENCY)
            except Exception:  # noqa: BLE001
                tiers = []
            tiers = [t for t in tiers if 5 <= (t.get("price_gbp") or 0) <= 10000]
            if len(tiers) >= 2:
                for t in tiers:
                    t["tier_label"] = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", t["tier_label"]))
                self._early_deadlines(tiers, re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", body))))
                return tiers
        return []

    @staticmethod
    def _early_deadlines(tiers: List[Dict[str, Any]], text: str) -> None:
        """'Early Registration (11 Nov 2026 - 17 Feb 2027)': the last date of the bracket is the early-bird deadline."""
        m = re.search(r"Early[^()]{0,30}\(([^)]{5,60})\)", text)
        ds = find_dates(m.group(1)) if m else []
        if ds:
            for t in tiers:
                if t.get("is_early_bird") and not t.get("early_bird_deadline"):
                    t["early_bird_deadline"] = ds[-1]["end"]
