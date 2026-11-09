"""EULAR Congress (congress.eular.org): single-congress family subclass.

This source is the Congress only; eular.org events and courses are source 134 and are not repeated here.
Hooks (each proven by the harness):
  * the line after the date line is the "EULAR Congress On-Demand Platform" button, which the family reader took
    as the venue: parse_place refuses it, and the venue ("held onsite at the Messe Berlin, Germany") is read from
    the registration page's opening sentence, never its "Location:" line (that is the Congress Dinner venue);
  * /congress-registration has a text grid "Categories / Until 31 March 2027 / From 1 April 2027" whose rows are
    "<category> / EUR n / EUR n" (some under a one-word group such as HPR, PARE, Company); parsed here. Rows
    shown as "-" (Student, Press) carry no public fee and are skipped. Prices are the public (non-member)
    rates incl. VAT; myEULAR member discounts (EUR 25 / 50) are stated separately and not applied;
  * the description is the Congress welcome paragraph (the first prose line is the registration announcement).
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines

_REG = "https://congress.eular.org/congress-registration"
_EUR_RE = re.compile(r"^EUR (\d[\d,]*)$")


class EularCongressExtractor(SingleCongressExtractor):
    HOME_URL = "https://congress.eular.org/"
    SOCIETY = "EULAR"
    EVENT_NAME = "EULAR Congress"
    DEFAULT_SPECIALTY = "Rheumatology"
    DEFAULT_CURRENCY = "EUR"
    REG_URLS = (_REG,)
    ABSTRACT_URLS = ("https://congress.eular.org/abstractgeneralinfo",)
    MAX_AUX_PAGES = 1

    def parse_place(self, raw):
        if re.search(r"on-demand|platform|sign in|register|congress|^(?:for|on|at)\b", raw or "", re.I):
            return None, None, None, False
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        for url, html in pages.items():
            if "registration" not in url:
                continue
            lines = html_lines(html)
            self._reg_lines = lines
            try:
                a = lines.index("REGISTRATION FEES")
                b = next(i for i in range(a, len(lines)) if lines[i].startswith("* A proof of status"))
            except (ValueError, StopIteration):
                continue
            seq = lines[a + 1:b]
            if not any(str(year) in l for l in lines[:12]):
                continue
            heads = [l for l in seq if re.match(r"^(Until|From) \d{1,2} [A-Z][a-z]+ \d{4}$", l)]
            if len(heads) != 2 or not heads[0].startswith("Until"):
                continue
            early_dl = datetime.strptime(heads[0][6:], "%d %B %Y").date()
            first_regular = heads[1]
            tiers: List[Dict[str, Any]] = []
            start = max(i for i, l in enumerate(seq) if l == "Fees include VAT**") + 1
            labels: List[str] = []
            amts: List[Optional[float]] = []

            def emit():
                parts = []
                for p in labels:
                    p = re.sub(r"[*]+$", "", p).strip()
                    if p.startswith("&") and parts:
                        parts[-1] = f"{parts[-1]} {p}"
                    else:
                        parts.append(p)
                if not parts or all(v is None for v in amts):
                    return
                cat = " ".join(parts) if parts[-1] != "Delegate" or len(parts) == 1 else f"{parts[0]} {parts[-1]}"
                cat = re.sub(r"\s*\(.*?\)$", "", cat) if "Dinner" not in cat else cat
                if len(amts) == 2 and None not in amts:
                    tiers.append({"tier_label": f"Congress registration · {cat} · Early bird (until {early_dl.day} {early_dl.strftime('%B %Y')})",
                                  "price_gbp": amts[0], "currency": "EUR", "is_early_bird": True, "early_bird_deadline": early_dl.isoformat()})
                    tiers.append({"tier_label": f"Congress registration · {cat} · Regular (from {first_regular[5:]})",
                                  "price_gbp": amts[1], "currency": "EUR", "is_early_bird": False, "early_bird_deadline": None})
                elif len(amts) == 1 and amts[0] is not None:
                    section = "Social event" if "Dinner" in cat else "Congress registration"
                    tiers.append({"tier_label": f"{section} · {cat}", "price_gbp": amts[0], "currency": "EUR",
                                  "is_early_bird": False, "early_bird_deadline": None})

            for l in seq[start:]:
                m = _EUR_RE.match(l)
                if m:
                    amts.append(float(m.group(1).replace(",", "")))
                elif l == "-":
                    amts.append(None)
                else:
                    if amts:
                        emit()
                        labels, amts = [], []
                    labels.append(l)
            emit()
            if tiers:
                return tiers
        return []

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        for l in (getattr(self, "_reg_lines", None) or [])[:40]:
            m = re.search(r"held onsite at the (Messe Berlin), ([A-Z][a-z]+),? on ", l)      # NOT the "Location:" line: that is the dinner venue
            if m:
                out.update(venue_name=m.group(1), city="Berlin", region=m.group(2), event_format="in_person")   # EULAR 2027 is "onsite in Berlin"
                break
        lines = html_lines(html)
        i = next((k for k, l in enumerate(lines) if l.startswith("We are excited to welcome you to the Messe Berlin")), None)
        if i is not None:
            out["description"] = " ".join(lines[i:i + 2])[:600]
        return out
