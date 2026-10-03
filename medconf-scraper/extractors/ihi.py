"""
Institute for Healthcare Improvement (IHI) — courses + flagship events.

Drupal 11 site, fully server-rendered (no bot protection). Two listings:

  1. https://www.ihi.org/learn/courses  — ONE page, ~24 cards (`.ihi-card`),
     no pagination (the "(24)" in the filter header is the real total; the
     recon estimate of ~75 was optimistic). Each card has a status label:
         "Begins Oct 14" / "Last Call Oct 21"  -> dated, bookable run  (KEPT)
         "In-Progress"                          -> already started, registration closed (skipped)
         "Interest List"                        -> no run scheduled yet (skipped)
         "On-Demand"                            -> self-paced, undated (skipped)
     Dated runs can live under /learn/courses/… or /learn/certifications/….

  2. https://www.ihi.org/connect/events — events calendar is a JS app, but the
     server HTML carries schema.org JSON-LD blocks (duplicated) for each event.
     `ConferenceEvent` entries (IHI Forum, Healthcare Improvement Forum Lisbon)
     are kept; plain `Event` entries are marketing "informational calls"
     (Zoom registration links) and are skipped.

Course detail pages: a JSON-LD `Event` (reliable start/end/attendance mode,
the end date can be years out for year-long programmes) plus a "Format: /
Begins: / Where: / Fee: / Groups of 3 or more:" key-value header. Fees are in
USD (`price_gbp` column holds the USD amount, `currency: "USD"` on each tier).
CPD text: "approved to provide N credits …" / "maximum of N AMA PRA Category 1
Credits".

Flagship events live on their own sites (events.ihi.org/forum, BMJ's
internationalforum.bmj.com/lisbon). The IHI Forum fee page is parsed; the
Lisbon site publishes no usable fee table, so it gets no tiers.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger


BASE_URL = "https://www.ihi.org"
COURSES_URL = BASE_URL + "/learn/courses"
EVENTS_URL = BASE_URL + "/connect/events"
FORUM_FEES_URL = "https://events.ihi.org/forum/fees-and-scholarships"

DEFAULT_SPECIALTY = "Quality Improvement & Patient Safety"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

_US_STATE = re.compile(r"^[A-Z]{2}$")


def _flat(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|svg)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html_lib.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _usd(text: str) -> Optional[float]:
    m = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _next_occurrence(mon: str, day: int, today: date) -> Optional[str]:
    """Card labels carry no year ("Begins Oct 14") — pick the first such date >= today."""
    mnum = _MONTHS.get(mon.lower()[:3])
    if not mnum:
        return None
    for yr in (today.year, today.year + 1):
        try:
            d = date(yr, mnum, day)
        except ValueError:
            return None
        if d >= today:
            return d.isoformat()
    return None


def _iso(ts: Optional[str]) -> Optional[str]:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", ts or "")
    return m.group(1) if m else None


def _ld_events(html: str) -> List[Dict[str, Any]]:
    out = []
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or ""):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        for item in (d if isinstance(d, list) else [d]):
            if isinstance(item, dict) and "Event" in str(item.get("@type", "")):
                out.append(item)
    return out


class IhiExtractor(BaseExtractor):

    def _get(self, url: str) -> Optional[str]:
        """Listing fetch with a small retry (fetch_html itself never raises)."""
        browser = getattr(self, "browser", None)
        for attempt in range(3):
            html = fetch_html(url, browser=browser)
            if html:
                return html
            logger.warning(f"IHI: fetch of {url} failed (attempt {attempt + 1}/3)")
            time.sleep(1.5)
        return None

    # ------------------------------------------------------------------ #
    # Phase A
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen: set = set()

        html = self._get(COURSES_URL)
        if not html:
            logger.warning("IHI: courses listing unavailable")
        else:
            skipped = {"on-demand": 0, "in-progress": 0, "interest-list": 0, "other": 0}
            cards = html.split('<div class="ihi-card">')[1:]
            for card in cards:
                lab_m = re.search(r'button--resource-label[^"]*">\s*([^<]*)', card)
                label = _flat(lab_m.group(1)) if lab_m else ""
                href_m = re.search(r'<h3>\s*<a href="([^"]+)"', card)
                title_m = re.search(r'<h3>.*?<span>(.*?)</span>', card, re.S)
                if not href_m or not title_m:
                    continue
                dm = re.match(r"(?i)(?:begins|last call)\s+([A-Za-z]{3})[a-z]*\s+(\d{1,2})", label)
                if not dm:
                    low = label.lower()
                    key = ("on-demand" if "on-demand" in low else "in-progress" if "progress" in low
                           else "interest-list" if "interest" in low else "other")
                    skipped[key] += 1
                    continue
                url = href_m.group(1)
                url = url if url.startswith("http") else BASE_URL + url
                if url in seen:
                    continue
                seen.add(url)
                loc_m = re.search(r'ihi-card-location">(.*?)</div>', card, re.S)
                loc = _flat(loc_m.group(1)) if loc_m else ""
                shells.append({
                    "title": _flat(title_m.group(1)),
                    "booking_url": url,
                    "start_date": _next_occurrence(dm.group(1), int(dm.group(2)), today),
                    "location_hint": loc or None,
                    "event_type": "course",
                })
            logger.info(f"IHI: {len(cards)} course cards, {len(shells)} dated runs kept; skipped {skipped}")

        ev_html = self._get(EVENTS_URL)
        if not ev_html:
            logger.warning("IHI: events page unavailable")
        else:
            for ld in _ld_events(ev_html):
                if ld.get("@type") != "ConferenceEvent":
                    continue
                url = ld.get("url")
                start, end = _iso(ld.get("startDate")), _iso(ld.get("endDate"))
                if not url or not start or (end or start) < today.isoformat() or url in seen:
                    continue
                seen.add(url)
                shells.append({
                    "title": html_lib.unescape(ld.get("name") or "").strip(),
                    "booking_url": url,
                    "start_date": start,
                    "end_date": end,
                    "location_hint": ld.get("location") if isinstance(ld.get("location"), str) else None,
                    "event_type": "conference",
                    "_ld_description": ld.get("description"),
                })
        return shells

    # ------------------------------------------------------------------ #
    # Phase B
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        if url.startswith(BASE_URL):
            return self._course_detail(page, shell, llm_call)
        return self._event_detail(page, shell, llm_call)

    # ---- courses ------------------------------------------------------ #
    def _course_detail(self, page: Page, shell: Dict[str, Any], llm_call) -> Dict[str, Any]:
        url = shell["booking_url"]
        html = ""
        try:
            html = page.content()
        except Exception:
            pass
        if "ihi-" not in html or len(html) < 5000:
            html = fetch_html(url, browser=getattr(self, "browser", None)) or html

        ld = next((e for e in _ld_events(html) if e.get("@type") == "Event"), {})
        i = html.find("<main")
        main_text = _flat(html[i:] if i >= 0 else html)
        # Header block runs from the title down to the Register button.
        hdr_m = re.search(r"Format:.*?(?=Register Now|Interest List|Apply\b|Group Registration|Please review|$)",
                          main_text)
        header = hdr_m.group(0) if hdr_m else ""

        def field(name: str) -> Optional[str]:
            m = re.search(rf"{name}:\s*(.*?)(?=\s(?:Format|Begins|Date|Register By|Duration|Where|Fee|Groups of 3 or more|"
                          rf"Sessions|Course Opens|Location):|$)", header)
            return m.group(1).strip() if m and m.group(1).strip() else None

        fmt_raw = field("Format") or ""
        where = field("Where")
        fee = field("Fee")
        group_fee = field("Groups of 3 or more")

        result: Dict[str, Any] = {"event_type": "course", "organiser_url": BASE_URL + "/"}

        start, end = _iso(ld.get("startDate")), _iso(ld.get("endDate"))
        if start:
            result["start_date"] = start
            if end and end != start:
                result["end_date"] = end
        mode = str(ld.get("eventAttendanceMode", ""))
        low = fmt_raw.lower()
        if "in-person" in low and "online" in low or mode.endswith("MixedEventAttendanceMode"):
            result["event_format"] = "hybrid"
        elif "online" in low or mode.endswith("OnlineEventAttendanceMode"):
            result["event_format"] = "online"
        elif "in-person" in low or mode.endswith("OfflineEventAttendanceMode"):
            result["event_format"] = "in_person"

        if where:
            result.update(self._place(where))

        result["pricing_tiers"] = self._course_tiers(fee, group_fee, header)

        text_after = main_text[main_text.find("Cancellation Policy"):] if "Cancellation Policy" in main_text else main_text
        cpd = re.search(r"(?i)approved to provide\s+(\d+(?:\.\d+)?)\s+(?:AMA PRA Category 1\s+)?credits", text_after) \
            or re.search(r"(?i)maximum of\s+(\d+(?:\.\d+)?)\s+AMA PRA Category 1 Credits", text_after)
        if cpd:
            v = float(cpd.group(1))
            result["cpd_points"] = int(v) if v == int(v) else v
        result["cpd_accredited"] = bool(re.search(r"(?i)jointly accredited by the Accreditation Council", text_after))

        # Skip the fee/cancellation boilerplate: the narrative starts after the header block.
        overview = re.sub(r"(?s)^.*?Cancellation Policy\s*", "", main_text, count=1)[:4000] if "Cancellation Policy" in main_text else main_text[:4000]
        result.update(self._soft(shell.get("title"), overview, ld.get("description"), llm_call))
        return {k: v for k, v in result.items() if v is not None}

    @staticmethod
    def _course_tiers(fee: Optional[str], group_fee: Optional[str], header: str) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        if fee is not None:
            price = _usd(fee)
            if price is None and re.search(r"(?i)\bfree\b|no cost|no charge", fee):
                price = 0.0
            if price is not None:
                tiers.append({"tier_label": "Registration · Individual · Standard", "price_gbp": price,
                              "currency": "USD", "is_early_bird": False})
        if group_fee is not None:
            gp = _usd(group_fee)
            if gp is not None:
                tiers.append({"tier_label": "Registration · Group of 3 or more (per person) · Standard",
                              "price_gbp": gp, "currency": "USD", "is_early_bird": False})
        return tiers

    @staticmethod
    def _place(where: str) -> Dict[str, Any]:
        parts = [p.strip() for p in where.split(",") if p.strip()]
        if not parts:
            return {}
        out: Dict[str, Any] = {"city": parts[0]}
        if len(parts) > 1:
            out["region"] = "United States" if _US_STATE.match(parts[1]) else parts[1]
        return out

    # ---- flagship events ---------------------------------------------- #
    def _event_detail(self, page: Page, shell: Dict[str, Any], llm_call) -> Dict[str, Any]:
        url = shell["booking_url"]
        result: Dict[str, Any] = {
            "event_type": "conference",
            "is_flagship": True,
            "event_format": "in_person",
            "organiser_url": BASE_URL + "/",
        }
        loc = shell.get("location_hint")
        if loc:
            result.update(self._place(loc))

        html = ""
        try:
            html = page.content()
        except Exception:
            pass
        if len(html) < 5000:
            html = fetch_html(url, browser=getattr(self, "browser", None)) or html
        text = _flat(html)

        # Venue (BMJ Lisbon site prints "CCL - Lisbon Congress Centre, Lisbon" under the date).
        vm = re.search(r"\d{1,2}-\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\s+(.{5,80}?)\s+Menu\b", text)
        if vm and "ihi.org" not in url:
            venue = vm.group(1).strip()
            result["venue_name"] = venue.split(",")[0].strip() if "," in venue else venue

        if "events.ihi.org/forum" in url:
            fees = self._get(FORUM_FEES_URL)
            result["pricing_tiers"] = self._forum_tiers(fees or "")
            result["cpd_accredited"] = bool(re.search(r"(?i)continuing education", text))

        result.update(self._soft(shell.get("title"), text[:3500], shell.get("_ld_description"), llm_call))
        return {k: v for k, v in result.items() if v is not None}

    @staticmethod
    def _forum_tiers(html: str) -> List[Dict[str, Any]]:
        """Fees page shows the CURRENT-year block first, then a stale previous-year
        block starting at "In-Person Registration" — only parse the first."""
        text = _flat(html)
        s = text.find("General Conference")
        e = text.find("In-Person Registration")
        block = text[s:e] if s >= 0 and e > s else (text[s:s + 2500] if s >= 0 else "")
        tiers: List[Dict[str, Any]] = []
        for m in re.finditer(r"(General Conference|Pre-Conference|Forum Hall Only Pass)\s*(\([^)]*\))?\s*:?\s*\$\s*([0-9,]+)", block):
            name, qual, price = m.group(1), (m.group(2) or "").strip("() "), float(m.group(3).replace(",", ""))
            cat = name if not qual else f"{name} ({qual})"
            tiers.append({"tier_label": f"Registration · {cat} · Standard", "price_gbp": price,
                          "currency": "USD", "is_early_bird": False})
        return tiers

    # ---- soft fields ---------------------------------------------------- #
    def _soft(self, title: Optional[str], text: str, ld_desc: Optional[str], llm_call) -> Dict[str, Any]:
        desc: Optional[str] = None
        spec: Optional[str] = None
        if text:
            prompt = (
                "From the event page text below, return strict JSON only: "
                '{"description": "30-50 word neutral summary using only the text, or null", '
                '"specialty": "primary clinical/healthcare area, e.g. Quality Improvement & Patient Safety, or null"}\n\n'
                f"Title: {title}\n\nPage text:\n{text[:2800]}"
            )
            try:
                raw = llm_call(prompt)
            except Exception:
                raw = None
            if raw:
                m = re.search(r"\{.*\}", raw, re.S)
                if m:
                    try:
                        p = json.loads(m.group(0))
                        desc = (p.get("description") or None)
                        spec = (p.get("specialty") or None)
                    except Exception:
                        pass
        # Publisher-written JSON-LD summary beats the LLM paraphrase when present.
        if ld_desc and len(_flat(ld_desc)) >= 60:
            desc = self._truncate(_flat(ld_desc))
        if isinstance(desc, str):
            desc = desc.strip() or None
        spec = spec or classify_specialty(title, ld_desc) or DEFAULT_SPECIALTY
        return {"description": desc, "specialty": spec}

    @staticmethod
    def _truncate(text: str, max_chars: int = 320) -> str:
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        last = max(cut.rfind(p + " ") for p in (".", "!", "?"))
        return cut[: last + 1] if last > max_chars * 0.5 else cut.rstrip() + "…"
