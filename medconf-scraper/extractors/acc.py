"""ACC Scientific Session (accscientificsession.acc.org): single-congress family subclass.

Hooks: venue from the Travel page ("will take place at the <venue>, located at ..."), fee tables parsed from
the raw <table>s on Registration Rates & Dates (one <h2> package per table, Early Bird / Advance / Regular
columns), abstract state from the Late-Breaking Clinical Trials page (the main abstract call closes in October
while late-breaking trials stay open to 1 Dec).
"""
import re
from datetime import date, datetime
from typing import Any, Dict, List

from .single_congress import SingleCongressExtractor, html_lines

_B = "https://accscientificsession.acc.org"
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _txt(frag: str) -> str:
    frag = re.sub(r"(?is)<br\s*/?>", " ", frag)
    frag = re.sub(r"<[^>]+>", " ", frag)
    return re.sub(r"\s+", " ", frag.replace("&amp;", "&").replace("&nbsp;", " ")).strip()


class AccExtractor(SingleCongressExtractor):
    HOME_URL = _B + "/"
    SOCIETY = "ACC"
    EVENT_NAME = "ACC Scientific Session"
    DEFAULT_SPECIALTY = "Cardiology"
    DEFAULT_CURRENCY = "USD"
    REG_URLS = (_B + "/Registration-and-Hotels/Registration-Rates-and-Dates",)
    ABSTRACT_URLS = (_B + "/Submit-Your-Science/Late-Breaking-Clinical-Trials", _B + "/Submit-Your-Science/Abstracts")
    VENUE_URLS = (_B + "/Registration-and-Hotels/Travel-And-Transportation",)

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            text = " ".join(html_lines(self._get(self.VENUE_URLS[0]) or ""))
            m = re.search(r"will take place at (?:the )?([A-Z][^,]{4,60}?),\s+located at", text)
            home = " ".join(html_lines(self._get(self.HOME_URL) or "")[:12])
            c = re.search(r"in ([A-Z][a-z]+(?: [A-Z][a-z]+)?),\s+([A-Z]{2})\b", home)
            if m and c:
                shells[0]["venue_raw"] = f"{m.group(1)}, {c.group(1)}, {c.group(2)}"
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts) and len(parts[2]) == 2:      # "Venue, City, ST"
            return parts[0], parts[1], "United States", False
        return super().parse_place(raw)

    @staticmethod
    def _early_deadline(txt: str, start: date):
        m = re.search(r"Until ([A-Z][a-z]{2,4})\.? (\d{1,2})", txt)
        if not m or m.group(1)[:3].lower() not in _MON:
            return None
        mon, day = _MON[m.group(1)[:3].lower()], int(m.group(2))
        for yr in (start.year, start.year - 1):          # latest date on or before the congress
            try:
                d = date(yr, mon, day)
            except ValueError:
                return None
            if d <= start:
                return d.isoformat()
        return None

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for html in pages.values():
            if "Registration Category" not in html:
                continue
            start = date(year, 1, 1)
            m = re.search(r"([A-Z][a-z]+)\.? (\d{1,2})\s*[–-]\s*\d{1,2}, (20\d\d)", html)   # not used for dates; year only
            for blk in re.finditer(r'(?is)<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|\Z)', html):
                pkg, rest = _txt(blk.group(1)), blk.group(2)
                tb = re.search(r"(?is)<table.*?</table>", rest)
                if not tb:
                    continue
                rows = re.findall(r"(?is)<tr.*?</tr>", tb.group(0))
                heads = [_txt(c) for c in re.findall(r"(?is)<th[^>]*>(.*?)</th>", rows[0])][1:]
                for tr in rows[1:]:
                    cat = re.search(r"(?is)<th[^>]*>(.*?)</th>", tr)
                    cells = [_txt(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)]
                    if not cat:
                        continue
                    label = re.sub(r"\s*Refer to .*$", "", _txt(cat.group(1))).strip()
                    for h, c in zip(heads, cells):
                        pm = re.fullmatch(r"\$\s?([\d,]+)", c)
                        if not pm:
                            continue
                        tf = None if h.lower() == "rate" else h
                        early = bool(tf and tf.lower().startswith("early bird"))
                        tiers.append({"tier_label": " · ".join(x for x in (pkg, label, tf) if x), "price_gbp": float(pm.group(1).replace(",", "")),
                                      "currency": "USD", "is_early_bird": early, "early_bird_deadline": self._early_deadline(h, self._start) if early else None})
            break
        return tiers

    def detail_from_html(self, html, url, shell, llm_call):
        self._start = date.fromisoformat(shell["start_date"])
        return super().detail_from_html(html, url, shell, llm_call)

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        for html in pages.values():
            text = " ".join(html_lines(html))
            m = re.search(r"Submission Dates:\s*([A-Z][a-z]{2,4})\.? (\d{1,2})\s*[-–]\s*([A-Z][a-z]{2,4})\.? (\d{1,2})", text)
            if not m or "Late-Breaking" not in text[:2000] and "late-breaking" not in text.lower():
                continue
            if "Late-Breaking" not in " ".join(html_lines(html)[:60]):
                continue
            m1, d1, m2, d2 = _MON.get(m.group(1)[:3].lower()), int(m.group(2)), _MON.get(m.group(3)[:3].lower()), int(m.group(4))
            if not (m1 and m2):
                continue
            start = date.fromisoformat(shell["start_date"])
            for yr in (start.year, start.year - 1):
                end = date(yr, m2, d2)
                if end <= start:
                    break
            op_yr = end.year if m1 <= m2 else end.year - 1
            opens = date(op_yr, m1, d1)
            if end >= today:
                out["abstract_open"] = opens <= today
                out["abstract_deadline"] = end.isoformat()
                out["abstract_deadline_note"] = "Late-breaking clinical trials; the main abstract call has closed"
                return
        super().apply_abstracts(out, pages, shell)
