"""Matrix fee-grid parser (ESSIC shape).

Congress microsites (Wix etc.) render fee grids as a header row of categories
followed by rows that start with a timeframe label and carry one price per
category:

    MD, PhD | Residents, Nurses & Care Workers | Students | Workshops
    ESSIC MEMBERS
    By July 15th   EUR300,00  EUR170,00  EUR90,00  EUR40,00
    After July 15th ...

or the transposed shape (columns = timeframes, rows = categories):

    Early bird | Standard | Late
    Member   300 350 400

Input is a line stream (rendered innerText, or HTML converted with
`html_to_lines`) where each grid cell sits on its own line or the row's
prices share one line. Tier labels follow the project convention
`[Group] · [Category] · [Timeframe]`. A currency symbol is mandatory, never
defaulted. European decimals ("300,00", "1.200,00") are understood.
"""

from __future__ import annotations
import html as _html
import re
from typing import Optional

SEP = " · "
_SYMS = {"£": "GBP", "$": "USD", "€": "EUR"}

_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_PRICE_RE = re.compile(
    rf"(?:(?P<s1>[£$€])\s?(?P<n1>{_NUM})|(?P<n2>{_NUM})\s?(?P<s2>[£$€]))")
_NA_RE = re.compile(r"^(?:-+|–|—|n/?a|free|tb[ac]|incl\.?|included)$", re.I)

_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*")
_TF_RE = re.compile(
    r"^(?:"
    r"(?:by|before|until|till|up\s+to|after|from|on|until)\s+[^\n]{1,30}"
    r"|(?:super[\s-]?)?early[\s-]?bird(?:\s+\w+){0,3}"
    r"|late(?:\s+\w+){0,2}|standard(?:\s+\w+)?|regular(?:\s+\w+)?"
    r"|on[\s-]?site(?:\s+\w+)?|advance(?:\s+\w+)?|final(?:\s+\w+)?"
    r")\W*$", re.I)
_TF_NEEDS_DATE_RE = re.compile(rf"\d|\b{_MONTH}\b|deadline|date|congress|meeting|event|registration", re.I)
_GROUP_RE = re.compile(r"\bmembers?\b|non[\s-]?members?|\bdelegates?\b|\bgroup\b|\bfull\b\s+rate", re.I)
_HEADING_RE = re.compile(r"\b(?:fees?|registration|prices?|pricing|rates?|tickets?)\b", re.I)


def html_to_lines(html: str) -> str:
    """HTML -> newline-separated cell text (block/cell boundaries become
    newlines). Scripts/styles dropped."""
    if not html:
        return ""
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html)
    h = re.sub(r"(?i)</?(?:p|div|li|ul|ol|tr|td|th|table|h[1-6]|br|section|article|span)\b[^>]*>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = _html.unescape(h).replace("​", "")
    return re.sub(r"[ \t\r\f\v]+", " ", h)


def parse_amount(raw: str) -> Optional[float]:
    """"300,00" -> 300.0, "1.200,00" -> 1200.0, "1,200.50" -> 1200.5, "1.200" -> 1200."""
    s = raw.strip()
    if not s or not re.fullmatch(_NUM, s):
        return None
    has_dot, has_com = "." in s, "," in s
    if has_dot and has_com:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        s = s.replace(thou, "").replace(dec, ".")
    elif has_com or has_dot:
        sep = "," if has_com else "."
        parts = s.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = "".join(parts)  # thousands separator(s)
        else:
            s = parts[0] + "." + parts[1]  # decimal
    try:
        return float(s)
    except ValueError:
        return None


def _cells(line: str) -> Optional[list]:
    """A line made only of price / n-a cells -> list of (price|None, currency|None).
    None when the line holds anything else."""
    s = line.strip()
    if not s:
        return None
    out: list = []
    pos = 0
    while pos < len(s):
        while pos < len(s) and s[pos] in " |\t/":
            pos += 1
        if pos >= len(s):
            break
        m = _PRICE_RE.match(s, pos)
        if m:
            amt = parse_amount(m.group("n1") or m.group("n2"))
            cur = _SYMS[m.group("s1") or m.group("s2")]
            out.append((amt, cur))
            pos = m.end()
            continue
        m2 = re.match(r"(-+|–|—|n/?a|free|tb[ac])(?=[\s|/]|$)", s[pos:], re.I)
        if m2:
            out.append((None, None))
            pos += m2.end()
            continue
        return None
    return out or None


def _is_timeframe(line: str) -> bool:
    s = line.strip().rstrip(":")
    if not s or len(s) > 40 or _cells(s):
        return False
    if not _TF_RE.match(s):
        return False
    if re.match(r"(?i)(by|before|until|till|up\s+to|after|from|on)\b", s):
        return bool(_TF_NEEDS_DATE_RE.search(s))
    return True


def _split_tf_prefix(line: str):
    """"By July 15th: EUR300 EUR170" -> ("By July 15th", cells). None when not that shape."""
    m = _PRICE_RE.search(line)
    if not m:
        return None
    head = line[:m.start()].strip().rstrip(":-–| ").strip()
    cells = _cells(line[m.start():])
    if head and cells and _is_timeframe(head):
        return head, cells
    return None


def _norm(lines) -> list:
    out = []
    for ln in (lines.splitlines() if isinstance(lines, str) else lines):
        s = ln.replace(" ", " ").replace("​", "").strip()
        if s:
            out.append(s)
    return out


_GENERIC_WORDS = {"members", "member", "non", "non-members", "non-member", "delegates",
                  "delegate", "group", "full", "rate", "rates", "fees", "fee"}


def _tidy(p: str) -> str:
    """ALL-CAPS cells: capitalise generic words only ("ESSIC MEMBERS" ->
    "ESSIC Members", "NON MEMBERS" -> "Non Members"); acronyms stay."""
    if p and p.isupper():
        return " ".join(w.capitalize() if w.lower() in _GENERIC_WORDS else w for w in p.split())
    return p


def _label(parts) -> str:
    parts = [_tidy(p) for p in parts if p]
    return SEP.join(p.strip(" :-–|*") for p in parts if p and p.strip(" :-–|*"))[:200]


def _tier(label: str, amt: float, cur: str, timeframe: str) -> dict:
    return {
        "tier_label": label, "price_gbp": amt, "currency": cur,
        "is_early_bird": bool(re.search(r"early|advance|by\b|before|until", timeframe, re.I)),
        "early_bird_deadline": None,
    }


def _row_oriented(lines: list) -> list:
    """Header of categories, then timeframe rows of prices."""
    tiers: list = []
    header: Optional[list] = None
    group: Optional[str] = None
    pend: list = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        row = None  # (timeframe, cells, next_i)
        tfp = _split_tf_prefix(ln)
        if tfp:
            row = (tfp[0], tfp[1], i + 1)
        elif _is_timeframe(ln):
            j, cells = i + 1, []
            while j < n:
                c = _cells(lines[j])
                if not c:
                    break
                cells.extend(c)
                j += 1
            if len([c for c in cells if c[0] is not None]) >= 2:
                row = (ln.rstrip(":"), cells, j)
        if row is None:
            cs = _cells(ln)
            if cs is None:
                if header is not None and len(ln) <= 40 and i + 1 < n and _is_timeframe(lines[i + 1]) \
                        and not _HEADING_RE.search(ln):
                    group = ln  # e.g. "NON MEMBERS" between two blocks
                    pend = []
                else:
                    pend.append(ln)
            i += 1
            continue
        tf, cells, nxt = row
        k = len(cells)
        if header is None or len(header) != k:
            cand = None
            for with_group in (True, False):
                take = k + 1 if with_group else k
                if len(pend) < take:
                    continue
                if with_group and not _GROUP_RE.search(pend[-1]):
                    continue
                hdr = pend[-take:-1] if with_group else pend[-take:]
                if any(_HEADING_RE.search(h) or len(h) > 60 or _is_timeframe(h) for h in hdr):
                    continue
                cand = (hdr, pend[-1] if with_group else group)
                break
            if cand is None:
                pend, i = [], nxt
                continue
            header, group = cand
        tf_clean = tf.strip(" :-–|")
        for col, (amt, cur) in zip(header, cells):
            if amt is None or amt <= 0 or amt > 50000:
                continue
            tiers.append(_tier(_label([group, col, tf_clean]), amt, cur, tf_clean))
        pend = []
        i = nxt
    return tiers


def _col_oriented(lines: list) -> list:
    """Header of timeframes (>=2 consecutive), then category rows of prices."""
    tiers: list = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_timeframe(lines[i]):
            i += 1
            continue
        j = i
        while j < n and _is_timeframe(lines[j]):
            j += 1
        header = [h.strip(" :-–|") for h in lines[i:j]]
        if len(header) < 2:
            i = j
            continue
        k = len(header)
        group: Optional[str] = None
        p = j
        found_rows = 0
        while p < n:
            ln = lines[p]
            inline = None
            m = _PRICE_RE.search(ln)
            if m and m.start() > 0:
                head = ln[:m.start()].strip(" :-–|")
                cells = _cells(ln[m.start():])
                if head and cells and len(cells) == k:
                    inline = (head, cells, p + 1)
            if inline is None and _cells(ln) is None and p + 1 < n:
                cells, q = [], p + 1
                while q < n:
                    c = _cells(lines[q])
                    if not c:
                        break
                    cells.extend(c)
                    q += 1
                if len(cells) == k and not _HEADING_RE.search(ln) and len(ln) <= 80:
                    inline = (ln.strip(" :-–|"), cells, q)
            if inline is None:
                if (found_rows == 0 or group is None) and _cells(ln) is None and len(ln) <= 40 \
                        and _GROUP_RE.search(ln) and p + 1 < n and _cells(lines[p + 1]) is None:
                    group = ln.strip(" :-–|")
                    p += 1
                    continue
                break
            label, cells, p = inline
            found_rows += 1
            for tf, (amt, cur) in zip(header, cells):
                if amt is None or amt <= 0 or amt > 50000:
                    continue
                tiers.append(_tier(_label([group, label, tf]), amt, cur, tf))
        i = max(p, j)
    return tiers


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAB_HDR_SKIP_RE = re.compile(r"^(?:qty|quantity|registration\s*type|ticket\s*type|category|type|price|fees?)$", re.I)


def _tab_grid(lines: list) -> list:
    """Tab-separated fee grid as rendered by registration forms (Scientex shape):

        Registration Type<TAB>Early Bird
        2026-05-31<TAB>Mid Term
        2026-09-15<TAB>Final Call
        2026-11-21<TAB>Qty
        Speaker Registration<TAB>$ 399<TAB>$ 499<TAB>$ 599<TAB>

    Each row is "label<TAB>price<TAB>price...". The timeframe header is spread
    over the lines above the first row, with ISO deadline dates interleaved
    (a date follows the timeframe it closes). Symbols may be separated from the
    amount by a space; a currency symbol is mandatory."""
    rows: list = []
    for idx, ln in enumerate(lines):
        if "\t" not in ln:
            continue
        parts = [p.strip() for p in ln.split("\t") if p.strip()]
        if len(parts) < 3 or _cells(parts[0]) is not None or len(parts[0]) > 80 \
                or not re.search(r"[A-Za-z]{3}", parts[0]):
            continue
        cells = _cells(" ".join(parts[1:]))
        if not cells or len([c for c in cells if c[0] is not None]) < 2 or len(cells) != len(parts) - 1:
            continue
        rows.append((idx, parts[0], cells))
    if not rows:
        return []
    tiers: list = []
    first = rows[0][0]
    toks: list = []
    for ln in lines[max(0, first - 8):first]:
        toks.extend(t.strip() for t in ln.split("\t") if t.strip())
    for i in range(len(toks) - 1, -1, -1):          # header starts at the "Registration Type" cell
        if re.match(r"(?i)registration\s*type|ticket\s*type|category$", toks[i]):
            toks = toks[i:]
            break
    frames: list = []                                # [(name, deadline|None)]
    for t in toks:
        if _TAB_HDR_SKIP_RE.match(t):
            continue
        if _ISO_DATE_RE.match(t):
            if frames and frames[-1][1] is None:
                frames[-1] = (frames[-1][0], t)
            continue
        if len(t) <= 30 and re.search(r"[A-Za-z]{3}", t):
            frames.append((t, None))
    for _, label, cells in rows:
        k = len(cells)
        if len(frames) < k:
            continue
        hdr = frames[-k:] if len(frames) > k else frames
        for (tf, dl), (amt, cur) in zip(hdr, cells):
            if amt is None or amt <= 0 or amt > 50000:
                continue
            t = _tier(_label([label, tf]), amt, cur, tf)
            if t["is_early_bird"] and dl:
                t["early_bird_deadline"] = dl
            tiers.append(t)
    return tiers


def parse_fee_matrix(text: str, max_tiers: int = 40, min_tiers: int = 4) -> list:
    """Tiers from a matrix fee grid in a line stream. [] when there is no
    grid of at least `min_tiers` prices. Row-oriented grids first, then the
    transposed shape."""
    lines = _norm(text or "")
    if len(lines) < 4:
        return []
    for fn in (_row_oriented, _col_oriented, _tab_grid):
        tiers = fn(lines)
        seen, uniq = set(), []
        for t in tiers:
            key = (t["tier_label"].lower(), t["price_gbp"])
            if key not in seen:
                seen.add(key)
                uniq.append(t)
        if len(uniq) >= min_tiers:
            return uniq[:max_tiers]
    return []
