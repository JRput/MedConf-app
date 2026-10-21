"""ASN Kidney Week (asn-online.org): single-congress family subclass.

Hooks: year-specific sub-pages (register-overview.aspx, important-dates.aspx) are linked from the landing page,
fees are <h4>program + <table> (Early | Standard | Onsite) blocks, and the Important Dates table lists the
date BEFORE its label (the family's key-date reader pairs them the other way round).
"""
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from .single_congress import SingleCongressExtractor, html_lines


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", frag).replace("&amp;", "&").replace("&nbsp;", " ")).strip()


def _parse_date(s: str, year: int) -> Optional[date]:
    m = re.search(r"([A-Z][a-z]+)\.? (\d{1,2})(?:,? (20\d\d))?", s)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3) or year}", "%b %d %Y").date()
    except ValueError:
        return None


class AsnOnlineExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.asn-online.org/education/kidneyweek/"
    SOCIETY = "ASN"
    EVENT_NAME = "ASN Kidney Week"
    DEFAULT_SPECIALTY = "Nephrology"
    DEFAULT_CURRENCY = "USD"

    def detail_from_html(self, html, url, shell, llm_call):
        def link(rx):
            m = re.search(r'href="([^"]*' + rx + r'[^"]*)"', html)
            return urljoin(url, m.group(1)) if m else None
        reg, dates = link(r"register-overview\.aspx"), link(r"important-dates\.aspx")
        self.REG_URLS = (reg,) if reg else ()
        self.ABSTRACT_URLS = (dates,) if dates else ()
        return super().detail_from_html(html, url, shell, llm_call)

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for html in pages.values():
            if "Registration Type" not in html:
                continue
            text = _txt(html)
            deadlines = {}
            for col, rx in (("Early", r"Early Registration Rate Deadline:\s*([A-Z][a-z]+ \d{1,2}, 20\d\d)"),
                            ("Standard", r"Standard Registration Rate Deadline:\s*([A-Z][a-z]+ \d{1,2}, 20\d\d)")):
                m = re.search(rx, text)
                if m:
                    deadlines[col] = _parse_date(m.group(1), year)
            for blk in re.finditer(r"(?is)<h4[^>]*>(.*?)</h4>(.*?)(?=<h4|\Z)", html):
                prog, rest = _txt(blk.group(1)), blk.group(2)
                tb = re.search(r"(?is)<table.*?</table>", rest)
                if not tb:
                    continue
                rows = re.findall(r"(?is)<tr.*?</tr>", tb.group(0))
                heads = [_txt(c) for c in re.findall(r"(?is)<th[^>]*>(.*?)</th>", rows[0])][1:]
                for tr in rows:
                    cells = [_txt(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)]
                    if len(cells) < 2:
                        continue
                    label = re.sub(r"\s*\([^)]*\)", "", cells[0]).strip()
                    for h, c in zip(heads, cells[1:]):
                        pm = re.fullmatch(r"\$\s?([\d,]+)", c)
                        if not pm:
                            continue
                        d = deadlines.get(h) if h == "Early" else None
                        tiers.append({"tier_label": f"{prog} · {label} · {h}", "price_gbp": float(pm.group(1).replace(",", "")), "currency": "USD",
                                      "is_early_bird": h == "Early", "early_bird_deadline": d.isoformat() if d else None})
            break
        return tiers

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        closes: List[date] = []
        opens_future = False
        for html in pages.values():
            lines = html_lines(html)
            for i, l in enumerate(lines[:-1]):
                d = _parse_date(l, today.year) if re.match(r"^[A-Z][a-z]+day,? [A-Z][a-z]+ \d{1,2}", l) else None
                if not d:
                    continue
                lab = lines[i + 1]
                if re.search(r"abstract", lab, re.I):
                    if re.search(r"closes", lab, re.I):
                        closes.append(d)
                    elif re.search(r"opens", lab, re.I) and d > today:
                        opens_future = True
        if closes:
            fut = sorted(c for c in closes if c >= today)
            dl = fut[0] if fut else max(closes)
            out["abstract_open"] = bool(fut) and not opens_future
            out["abstract_deadline"] = dl.isoformat()
            return
        super().apply_abstracts(out, pages, shell)
