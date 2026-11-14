"""EHA Congress (ehaweb.org/connect-network/eha2027-congress): single-congress family subclass.

ehaweb.org only. congress.ehaweb.org (m-anage registrar, robots Disallow: /) is never fetched; the fee grid is
published on the ehaweb.org registration page, so fees do not need that host.
Hooks (each proven by the harness / offline run on the saved pages):
  * the date line "June 10-13, 2027" is followed by the line "| Barcelona, Spain": ACCEPT_PLACE_RE takes it as the place;
  * the venue is under "Location" on the details-and-deadlines page ("Fira Barcelona Gran Via (North access)");
  * the registration page has two text grids (Hybrid / Virtual) of "<category> / EUR n / EUR n / EUR n" under
    Early / Regular / Late, with the cut-off dates in "Early fee: until May 3, 2027" lines; parsed here. Prices are the
    public rates incl. VAT; individual registration opens 1 January 2027 on the m-anage host (never fetched);
  * the family classifier took "June 13" (late hybrid registration) as the abstract deadline: the deadline is read from
    "<date>: Deadline for abstract submission..." and the open date from "<date>: Abstract submission ... open".
"""
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines

_MON = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_AMT_RE = re.compile(r"^€\s?(\d[\d,]*)$")
_CUT_RE = re.compile(rf"^(Early|Regular|Late) fee: until (?:[^=]*= )?({_MON} \d{{1,2}}, 20\d\d)")
_ABS_DL_RE = re.compile(rf"^({_MON} \d{{1,2}}, 20\d\d)(?: \([^)]*\))?:\s*Deadline for abstract submission\b(?! .*late)", re.I)
_ABS_OPEN_RE = re.compile(rf"^({_MON} \d{{1,2}}, 20\d\d):\s*Abstract submission .*\bopen", re.I)
_LBA_RE = re.compile(rf"^({_MON} \d{{1,2}}, 20\d\d)(?: \([^)]*\))?:\s*Deadline for late-breaking abstract submission", re.I)


def _d(s: str) -> date:
    return datetime.strptime(s, "%B %d, %Y").date()


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


class EhaCongressExtractor(SingleCongressExtractor):
    HOME_URL = "https://ehaweb.org/connect-network/eha2027-congress"
    SOCIETY = "EHA"
    EVENT_NAME = "EHA Congress"
    DEFAULT_SPECIALTY = "Haematology"
    DEFAULT_CURRENCY = "EUR"
    ACCEPT_PLACE_RE = re.compile(r"^\|\s*[A-Z][\w .'-]+,\s*[A-Z][\w .'-]+$")
    REG_URLS = ("https://ehaweb.org/connect-network/eha2027-congress/eha2027-registration",)
    ABSTRACT_URLS = ("https://ehaweb.org/connect-network/eha2027-congress/eha2027-abstract-submission",)
    VENUE_URLS = ("https://ehaweb.org/connect-network/eha2027-congress/eha2027-details-and-deadlines",)
    MAX_AUX_PAGES = 1

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        # The registration page has "Hybrid Registration fees" and "Virtual Registration fees";
        # the home page carries no hybrid wording, so the family rule never fires (review 2026-11-14).
        if out.get("event_format") == "in_person":
            out["event_format"] = "hybrid"
        return out

    def venue_from_lines(self, lines):
        for i, l in enumerate(lines[:-1]):
            if l == "Location" and lines[i + 1][:1].isupper():
                return re.sub(r"\s*\(.*?\)\s*$", "", lines[i + 1]).strip()
        return None

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        for url, html in pages.items():
            if "registration" not in url:
                continue
            lines = html_lines(html)
            tiers: List[Dict[str, Any]] = []
            mode = None
            cuts: Dict[str, date] = {}
            rows: List[tuple] = []
            for i, l in enumerate(lines):
                if re.match(r"^(Hybrid|Virtual) Registration fees$", l):
                    mode = l.split()[0]
                    j = i + 1
                    cat: Optional[str] = None
                    amts: List[float] = []
                    block: List[tuple] = []
                    while j < len(lines) and not re.match(r"^(Early|Regular|Late) fee: until", lines[j]) and not re.match(r"^(Hybrid|Virtual) Registration fees$", lines[j]):
                        m = _AMT_RE.match(lines[j])
                        if m:
                            amts.append(float(m.group(1).replace(",", "")))
                            if len(amts) == 3 and cat:
                                block.append((cat, amts))
                                cat, amts = None, []
                        elif lines[j] in ("CATEGORY \\ DEADLINE", "Early", "Regular", "Late") or lines[j].startswith(("All fees", "*Participants")):
                            pass
                        elif not amts:
                            cat = (cat + " " + lines[j]) if cat and not cat.endswith("*") and lines[j].startswith("(") else lines[j]
                        j += 1
                    cuts = {}
                    while j < len(lines) and (cm := _CUT_RE.match(lines[j])):
                        cuts[cm.group(1)] = _d(cm.group(2))
                        j += 1
                    if len(cuts) == 3 and block:
                        rows.append((mode, block, cuts))
            for mode, block, cuts in rows:
                for cat, amts in block:
                    name = re.sub(r"\*$", "", cat)
                    if cat.endswith("*"):
                        name += " (36 or younger)"
                    for (stage, price) in zip(("Early", "Regular", "Late"), amts):
                        dl = cuts[stage]
                        tf = {"Early": f"Early bird (until {_fmt(dl)})", "Regular": f"Regular (until {_fmt(dl)})", "Late": f"Late (until {_fmt(dl)})"}[stage]
                        tiers.append({"tier_label": " · ".join([f"{mode} registration", name, tf]), "price_gbp": price, "currency": "EUR",
                                      "is_early_bird": stage == "Early", "early_bird_deadline": dl.isoformat() if stage == "Early" else None})
            if tiers:
                return tiers
        return []

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        dls, opens, lba = [], [], []
        for html in pages.values():
            for l in html_lines(html):
                for rx, bucket in ((_ABS_DL_RE, dls), (_ABS_OPEN_RE, opens), (_LBA_RE, lba)):
                    m = rx.match(l)
                    if m:
                        bucket.append(_d(m.group(1)))
        if not dls:
            return super().apply_abstracts(out, pages, shell)
        dl = min(dls)
        o = min(opens) if opens else None
        out["abstract_open"] = bool(o is None or o <= today) and dl >= today
        out["abstract_deadline"] = dl.isoformat()
        notes = []
        if o and o > today:
            notes.append(f"Submission opens {_fmt(o)}")
        if lba:
            notes.append(f"Late-breaking abstracts close {_fmt(max(lba))}")
        if notes:
            out["abstract_deadline_note"] = "; ".join(notes)
