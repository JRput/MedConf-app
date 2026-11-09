"""ACR Convergence (rheumatology.org/meetings/acr-convergence): single-congress family subclass.

Hooks (each proven by the harness):
  * the event page lists "Date: November 6-11, 2026" / "Location: Orlando, FL" as label lines, so the
    base class read the label "Date" as a city: parse_place strips the "Location:" label and refuses "Date";
  * the venue name only appears in the registration page prose ("... in the West Building of the Orange
    County Convention Center in Orlando, Florida");
  * the fee grids on /annual-meeting-registration (Member / Nonmember x Early / General rate x In Person Plus /
    In Person, plus On Demand and guest pass) are text lines the family matrix reader cannot pair;
  * the page's "Category 1 CME credits" wording is read by the base class as 1 credit and the real figure
    (182.75, live + on demand) is above its sanity cap, so cpd_points is dropped;
  * the first prose line is the site's login banner: the description is the paragraph after "Register Now".
"""
import re
from datetime import date
from typing import Any, Dict, List, Optional

from .single_congress import _STATE_NAMES as _US_STATE_NAMES, SingleCongressExtractor, html_lines

_REG = "https://rheumatology.org/annual-meeting-registration"
_RATE_RE = re.compile(r"^(Early|General) Rate \(through ([A-Z][a-z]+ \d{1,2})\)$")
_MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                           "august", "september", "october", "november", "december"])}


def _usd(s: str) -> Optional[float]:
    m = re.fullmatch(r"\$\s?(\d[\d,]*(?:\.\d\d)?)", s.strip())
    return float(m.group(1).replace(",", "")) if m else None


class AcrExtractor(SingleCongressExtractor):
    HOME_URL = "https://rheumatology.org/meetings/acr-convergence/"
    SOCIETY = "ACR"
    EVENT_NAME = "ACR Convergence"
    DEFAULT_SPECIALTY = "Rheumatology"
    DEFAULT_CURRENCY = "USD"
    ACCEPT_PLACE_RE = re.compile(r"^Location:\s", re.I)
    REG_URLS = (_REG,)
    VENUE_URLS = (_REG,)

    def _edition_from(self, url, html):
        self._page_fetched = True                      # the family calls this only with a fetched page
        return super()._edition_from(url, html)

    def list_shells_override(self):
        self.verified_empty = None
        self._page_fetched = False
        shells = super().list_shells_override()
        if not shells and self._page_fetched:
            # Page fetched, but its edition has ended and it names no later dates (checked 2026-11-09: only
            # "ACR Convergence 2027 Financial Relationships Disclosures (to be announced)").
            self.verified_empty = "ACR Convergence 2026 ended; no 2027 edition dates announced on the event page"
        return shells

    def parse_place(self, raw):
        raw = re.sub(r"^\s*Location:\s*", "", raw or "")
        if re.match(r"(?i)^date\b", raw.strip()):
            return None, None, None, False
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 3 and all(parts) and parts[2].lower() in _US_STATE_NAMES:      # "Venue, City, State"
            return parts[0], parts[1], "United States", False
        return super().parse_place(raw)

    def venue_from_lines(self, lines: List[str]) -> Optional[str]:
        for l in lines[:120]:
            m = re.search(r"\bof the ([A-Z][\w &'-]+?(?:Center|Centre|Hall|Hotel|Complex)) in ([A-Z][a-z]+(?: [A-Z][a-z]+)?), ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", l)
            if m:
                return f"{m.group(1)}, {m.group(2)}, {m.group(3)}"
        return None

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        today = date.today()
        for url, html in pages.items():
            if "registration" not in url:
                continue
            lines = html_lines(html)
            if not any(re.search(rf"ACR Convergence {year}\b", l) for l in lines[:90]):
                continue                                   # the page still describes another edition
            tiers: List[Dict[str, Any]] = []
            seen = set()

            def add(label: str, amt: float, early: bool, dl: Optional[date]) -> None:
                if label in seen:
                    return
                seen.add(label)
                tiers.append({"tier_label": label, "price_gbp": amt, "currency": "USD", "is_early_bird": early,
                              "early_bird_deadline": dl.isoformat() if (early and dl) else None})

            band = rate = None
            deadline: Optional[date] = None
            cols: List[str] = []
            i = 0
            while i < len(lines):
                l = lines[i]
                if l in ("Member Rates", "Nonmember Rates"):
                    band, rate, cols = ("Member" if l.startswith("Member") else "Nonmember"), None, []
                elif (m := _RATE_RE.match(l)) and band:
                    mon, day = m.group(2).split()
                    deadline = date(year, _MONTHS[mon.lower()], int(day))
                    rate = (m.group(1), deadline)
                    cols = []
                elif rate and l == "Audience":
                    cols = []
                    j = i + 1
                    while j < len(lines) and lines[j] in ("In Person Plus", "In Person"):
                        cols.append(lines[j])
                        j += 1
                    i = j - 1
                elif rate and cols and l not in ("Optional Add-On Sessions", "Additional Registration Options") and not l.startswith(("ACR Convergence On Demand", "-->")):
                    vals = []
                    j = i + 1
                    while j < len(lines) and len(vals) < len(cols) and (lines[j] == "NA" or _usd(lines[j]) is not None):
                        vals.append(lines[j])
                        j += 1
                    if len(vals) == len(cols) and _usd(l) is None and l != "NA":
                        if rate[1] >= today:               # an expired early-rate column is not offered any more
                            for c, v in zip(cols, vals):
                                if _usd(v) is not None:
                                    add(f"{c} · {band} · {l} · {rate[0]} rate (through {rate[1].strftime('%B')} {rate[1].day})",
                                        _usd(v), rate[0] == "Early", rate[1])
                        i = j - 1
                m2 = re.match(r"^ACR Convergence On Demand: (\$[\d,]+)$", l)
                if m2 and band and _usd(m2.group(1)) is not None:
                    add(f"On Demand · {band}", _usd(m2.group(1)), False, None)
                m3 = re.match(r"^(Guest Pass|Shuttle Pass): (\$[\d,]+)", l)
                if m3 and _usd(m3.group(2)) is not None:
                    add(f"Add-on · {m3.group(1)}", _usd(m3.group(2)), False, None)
                i += 1
            if tiers:
                return tiers
        return []

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        out.pop("cpd_points", None)
        lines = html_lines(html)
        i = next((k for k, l in enumerate(lines) if l == "Register Now"), None)
        if i is not None:
            d = next((l for l in lines[i + 1:i + 4] if len(l) > 80), None)
            if d:
                out["description"] = d[:600]
        return out
