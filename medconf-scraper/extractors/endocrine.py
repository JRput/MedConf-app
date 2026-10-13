"""Endocrine Society (ENDO, CEU, joint Keystone meetings): family subclass with a hand-built listing.

The hub `/meetings-and-events` has no event cards. Three places name the upcoming meetings:
  * the hub itself: "Register now for Clinical Endocrinology Update (CEU) 2026, taking place online October 22-24."
    (the meeting site ceu2026.endocrine.org is EventScribe behind Cloudflare: 403 to scripts, so CEU keeps shell values);
  * `/endo-future-meetings`: "ENDO 2027 / June 5-7, 2027 / Toronto, ON, Canada" blocks (fees not yet published);
  * `/keystone-conference`: "Title (February 1-4, 2027 | Keystone, Colo.)" with links to keystonesymposia.org, whose
    `/meeting/pricing/<CODE>` page holds the USD fee grid (In Person / Livestream / On Demand x Early / Student / Regular).
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive, _iso, _mon

_ROOT = "https://www.endocrine.org"
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_CEU_RE = re.compile(rf"Clinical Endocrinology Update \(CEU\) (\d{{4}}),? taking place (online|in [^.]+?)\s+({_MONTH})\s+(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})")
_ENDO_RE = re.compile(rf"^ENDO (\d{{4}})$")
_RANGE_RE = re.compile(rf"^({_MONTH})\s*(\d{{1,2}})\s*[-–]\s*(?:({_MONTH})\s*)?(\d{{1,2}}),\s*(\d{{4}})$")
_KEY_DATE_RE = re.compile(rf"\(({_MONTH})\s+(\d{{1,2}})\s*[-–]\s*(?:({_MONTH})\s+)?(\d{{1,2}}),\s*(\d{{4}})\s*\|\s*([^)]+)\)")
_KEY_LINK_RE = re.compile(r'(?is)<a\b[^>]*href="(https://www\.keystonesymposia\.org/[^"]+/meeting/([A-Za-z0-9]+))"[^>]*>(.*?)</a>')
_PRICE_RE = re.compile(r"^\$\s?(\d[\d,]*(?:\.\d\d)?)\s*USD$")
_US_STATES = {"CO": "Colorado"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


class EndocrineExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/meetings-and-events"
    SOCIETY = "Endocrine Society"
    DEFAULT_SPECIALTY = "Endocrinology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "USD"
    DEFAULT_EVENT_TYPE = "conference"

    # ---- listing -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []

        def add(title, url, s, e, venue_raw, cat):
            if s and (e or s) >= today:
                shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": s, "end_date": e or s,
                               "start_time": None, "venue_raw": venue_raw, "category": cat})

        hub = self._fetch(self.LISTING_URL) or ""
        hub_text = " ".join(html_to_lines(hub))
        m = _CEU_RE.search(hub_text)
        if m:
            yr, fmt, mon, d1, d2 = m.groups()
            link = re.search(rf'href="(https://ceu{yr}\.endocrine\.org[^"]*)"', hub)
            add(f"Clinical Endocrinology Update (CEU) {yr}", (link.group(1) if link else f"https://ceu{yr}.endocrine.org/").rstrip("/") + "/",
                _iso(int(yr), _mon(mon), int(d1)), _iso(int(yr), _mon(mon), int(d2)), "Online" if fmt == "online" else None, "CEU")
        time.sleep(self.REQUEST_GAP_S)

        fut = self._fetch(_ROOT + "/meetings-and-events/endo-future-meetings") or ""
        lines = dedupe_consecutive(html_to_lines(fut))
        for i, l in enumerate(lines):
            em = _ENDO_RE.match(l)
            if not em or i + 2 >= len(lines):
                continue
            dm = _RANGE_RE.match(re.sub(r"(\d)–", r"\1-", lines[i + 1]).replace(" ", " ").replace("June16", "June 16"))
            if not dm:
                continue
            m1, d1, m2, d2, yr = dm.groups()
            add(f"ENDO {em.group(1)}", f"{_ROOT}/meetings-and-events/endo-future-meetings#endo-{em.group(1)}",
                _iso(int(yr), _mon(m1), int(d1)), _iso(int(yr), _mon(m2 or m1), int(d2)), lines[i + 2], "ENDO annual meeting")
        time.sleep(self.REQUEST_GAP_S)

        key = self._fetch(_ROOT + "/meetings-and-events/keystone-conference") or ""
        for lm in _KEY_LINK_RE.finditer(key):
            href, title = lm.group(1), _clean(lm.group(3))
            km = _KEY_DATE_RE.search(_clean(key[lm.end():lm.end() + 400]))
            if not km or not title:
                continue
            m1, d1, m2, d2, yr, place = km.groups()
            add(title, href, _iso(int(yr), _mon(m1), int(d1)), _iso(int(yr), _mon(m2 or m1), int(d2)), place, "Keystone joint meeting")
        logger.info(f"Endocrine Society listing: {len(shells)} shells")
        return shells or None

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        cat = shell.get("category")
        out: Dict[str, Any] = {"society": self.SOCIETY, "event_type": "conference", "specialty": "Endocrinology",
                               "start_date": shell["start_date"], "end_date": shell["end_date"]}
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html or "")))
        if cat == "CEU":
            out["event_format"] = "online" if shell.get("venue_raw") == "Online" else None
            out["description"] = "Endocrine Society's Clinical Endocrinology Update (CEU): an annual clinical education meeting for endocrinology practitioners."
            out["description"] += " Held online." if out["event_format"] else ""
            if not out["event_format"]:
                out.pop("event_format")
            return out
        if cat == "ENDO annual meeting":
            parts = [p.strip() for p in (shell.get("venue_raw") or "").split(",") if p.strip()]
            if parts:
                out["city"] = parts[0]
                out["region"] = {"ON": "Canada"}.get(parts[1], None) if len(parts) > 1 and len(parts[1]) == 2 else None
                if len(parts) > 2:
                    out["region"] = parts[-1]
                elif len(parts) == 2 and len(parts[1]) == 2 and not out.get("region"):
                    out["region"] = "United States"          # "Boston, MA"
                out["event_format"] = "in_person"
            intro = next((l for l in lines if l.startswith("The Society's ENDO is")), None)
            if intro:
                out["description"] = intro.split(" Mark your calendars")[0][:600]
            return out
        # Keystone joint meeting
        hl = next((l for l in lines if re.match(rf"^{_MONTH}\s+\d{{1,2}}\s*[–-]", l) and "|" in l), None)
        if hl:
            loc = [p.strip() for p in hl.split("|", 1)[1].split(",") if p.strip()]
            if len(loc) >= 3:
                out["venue_name"], out["city"], out["region"] = loc[0], loc[1], loc[-1]
            elif len(loc) == 2:
                out["city"], out["region"] = loc
        out["event_format"] = "hybrid" if any(l == "Livestream" for l in lines) else "in_person"
        i = next((k for k, l in enumerate(lines) if l.startswith("About This Meeting")), None)
        if i is not None:
            para = next((l for l in lines[i + 1:i + 4] if len(l) > 80), None)
            if para:
                out["description"] = para[:600]
        pm = re.search(r"/meeting/([A-Za-z0-9]+)$", shell["booking_url"])
        if pm:
            time.sleep(self.REQUEST_GAP_S)
            pg = fetch_html(shell["booking_url"].rsplit("/meeting/", 1)[0] + "/meeting/pricing/" + pm.group(1).upper(), browser=getattr(self, "browser", None))
            if pg:
                tiers = self._keystone_tiers(dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", pg))))
                if tiers:
                    out["pricing_tiers"] = tiers
        return out

    @staticmethod
    def _keystone_tiers(lines: List[str]) -> List[Dict[str, Any]]:
        """Fee grid, second layout: product heading (In Person / Livestream / On Demand), then
        'Early Registration:' [+ 'Deadline: Dec. 2, 2026'], 'Student Rate:', 'Regular Rate:' each followed by '$1145 USD'."""
        start = next((i for i, l in enumerate(lines) if l == "Register" and i + 1 < len(lines) and lines[i + 1] in ("Early Registration:", "Student Rate:", "Regular Rate:")), None)
        if start is None:
            return []
        tiers, product, kind, deadline = [], None, None, None
        for l in lines[max(0, start - 1):]:
            if re.match(r"(?i)^(scholarships|important information)", l):
                break
            if l in ("In Person", "Livestream", "On Demand", "Multiproduct"):
                product, kind, deadline = l, None, None
                continue
            if product in (None, "Multiproduct"):
                continue
            km = re.match(r"^(Early Registration|Student Rate|Regular Rate):$", l)
            if km:
                kind = km.group(1)
                continue
            dm = re.match(rf"^Deadline:\s*({_MONTH})\.?\s+(\d{{1,2}}),\s*(\d{{4}})$", l)
            if dm and kind == "Early Registration":
                deadline = _iso(int(dm.group(3)), _mon(dm.group(1)), int(dm.group(2)))
                continue
            pm = _PRICE_RE.match(l)
            if pm and kind:
                label = {"Early Registration": "Early rate", "Student Rate": "Student rate", "Regular Rate": "Regular rate"}[kind]
                early = kind == "Early Registration"
                tiers.append({"tier_label": f"{product} · {label}", "price_gbp": float(pm.group(1).replace(",", "")), "currency": "USD",
                              "is_early_bird": early, "early_bird_deadline": deadline if early else None})
                kind = None
        return tiers
