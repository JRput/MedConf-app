"""RSNA Annual Meeting (rsna.org): single-congress family subclass with a bespoke fee-matrix hook.

Pricing page = three matrices (member packages, select member categories, non-member registrant types)
with column headers on separate lines, which the generic fee parser mislabels. `fees_from_pages` reads them.
"""
import re
from typing import Any, Dict, List

from .single_congress import SingleCongressExtractor, html_lines

_AMT_RE = re.compile(r"\$\s?([\d,]+)")
_ONLY_AMT_RE = re.compile(r"^\$\s?[\d,]+(?:\s+\$\s?[\d,]+)?(?:\s+Virtual Access)?$")


def _tier(label: str, amount: str) -> Dict[str, Any]:
    return {"tier_label": label, "price_gbp": float(amount.replace(",", "")), "currency": "USD",
            "is_early_bird": False, "early_bird_deadline": None}


class RsnaExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.rsna.org/annual-meeting"
    SOCIETY = "RSNA"
    EVENT_NAME = "RSNA Annual Meeting"
    DEFAULT_SPECIALTY = "Radiology"
    DEFAULT_CURRENCY = "USD"
    REG_URLS = ("https://www.rsna.org/annual-meeting/attendee-resources/pricing-and-registration",)
    ABSTRACT_URLS = ("https://www.rsna.org/annual-meeting/abstract-submission",)

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            page = self._get(self.REG_URLS[0]) or ""
            text = " ".join(html_lines(page))
            if re.search(r"McCormick Place", text) and re.search(r"seeing you in Chicago|in Chicago", text):
                shells[0]["venue_raw"] = "McCormick Place, Chicago, United States"
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    @staticmethod
    def _tables(html: str) -> List[List[List[str]]]:
        """Raw <table> -> rows of cell text (the line view drops repeated consecutive cells like $600 | $600)."""
        out = []
        for t in re.findall(r"(?is)<table.*?</table>", html):
            rows = []
            for tr in re.findall(r"(?is)<tr.*?</tr>", t):
                cells = [re.sub(r"\s+", " ", re.sub(r"(?is)<br\s*/?>", " ", c)) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", re.sub(r"(?is)</p>\s*(?=<p|<strong)", " / ", tr))]
                cells = [re.sub(r"<[^>]+>", " ", c).replace("&amp;", "&").replace("&nbsp;", " ").strip() for c in cells]
                cells = [re.sub(r"\s+", " ", c) for c in cells]
                if cells:
                    rows.append(cells)
            out.append(rows)
        return out

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for html in pages.values():
            lines = html_lines(html)
            if not any(l.startswith("Registration Rates for Non-Members") for l in lines):
                continue
            # 1) member packages: "$in-person $virtual" (Basic splits them over two lines)
            for name in ("Full Access", "Standard", "Basic"):
                i = next((k for k, l in enumerate(lines) if l.startswith(f"{name} Members")), None)
                if i is None:
                    continue
                amts: List[str] = []
                for l in lines[i + 1:i + 14]:
                    if re.match(r"^Register Now$", l):
                        break
                    if _ONLY_AMT_RE.match(l):
                        amts += _AMT_RE.findall(l)
                if amts:
                    tiers.append(_tier(f"Registration · RSNA Member ({name}) · In Person & Virtual Access", amts[0]))
                if len(amts) > 1:
                    tiers.append(_tier(f"Registration · RSNA Member ({name}) · Virtual Access Only", amts[1]))
            # 2) + 3) the two tables: first column = category, then one price per header column
            for rows in self._tables(html):
                if len(rows) < 2 or not rows[0][0].startswith(("Membership Category", "Registrant Type")):
                    continue
                kind = "RSNA Member" if rows[0][0].startswith("Membership") else "Non-Member"
                cols = rows[0][1:]
                for row in rows[1:]:
                    label = re.sub(r"\s*\*+", "", row[0]).strip()
                    label = re.sub(r" Includes RSNA and AAPM members$", "", label)
                    label = re.sub(r"\s*/\s*", "/", label).replace("Other/Non-Physician/Non-Industry", "Other (Non-Physician/Non-Industry)")
                    for col, cell in zip(cols, row[1:]):
                        m = re.fullmatch(r"\$\s?([\d,]+)", cell)
                        if m:
                            tiers.append(_tier(f"Registration \u00b7 {kind} \u00b7 {label} \u00b7 {col}", m.group(1)))
            break
        return tiers
