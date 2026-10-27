"""Shared amount / currency parser — the ONE place that reads a fee.

Before this module every layer (pricing tables, single-congress, Tribe, WordPress,
ESMO, vision, remediator) had its own regex and its own idea of what "1.500,00",
"S$465" or "kr 2,500" meant, and several of them silently fell back to GBP. Rules:

* Nothing here ever defaults a currency. `Money.currency` / `detect_currency()`
  return None when the text does not say, and the caller must drop or skip.
* Decimal rule: the LAST separator followed by exactly 1-2 digits is the decimal
  mark; followed by 3 digits it is a thousands mark. Apostrophe / space / NBSP /
  thin-space are always thousands marks. For 0-decimal currencies (JPY, KRW, HUF...)
  "." / "," before 3 digits is always thousands.
* Ambiguous symbols: bare "$" = USD unless prefixed (A$ C$ NZ$ S$ HK$ US$ R$ MX$)
  or the text/context names another dollar; "¥" = JPY unless CNY/RMB/元 is named;
  "kr" needs SEK/NOK/DKK in the text/context (else currency None); "Fr." = CHF.
* Amount 0 is returned as 0 ("£0.00 shipping"); whether it is a fee is the caller's call.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

__all__ = [
    "Money", "CURRENCIES", "KNOWN_CODES", "parse_amount", "find_amounts", "parse_number",
    "detect_currency", "normalize_currency", "plausible", "max_amount", "prompt_symbol_table",
]


# ── ISO-4217 table ──────────────────────────────────────────────────────────────
# code: (symbols, decimals, sane max amount for ONE registration fee, names)
# Symbols listed here are the ones that identify the code UNAMBIGUOUSLY on their own
# or as written ("S$"); bare "$", "¥", "kr" are resolved by the rules above.
_ROWS: Dict[str, Tuple[Tuple[str, ...], int, float, Tuple[str, ...]]] = {
    "GBP": (("£",), 2, 50_000, ("sterling", "pound", "pounds")),
    "EUR": (("€",), 2, 50_000, ("euro", "euros")),
    "USD": (("US$", "U$S"), 2, 50_000, ("us dollar", "us dollars", "u.s. dollars")),
    "CHF": (("Fr.", "SFr.", "SFr", "Fr"), 2, 50_000, ("swiss franc", "swiss francs")),
    "SGD": (("S$", "SG$", "SGD$"), 2, 70_000, ("singapore dollar", "singapore dollars")),
    "HKD": (("HK$",), 2, 400_000, ("hong kong dollar", "hong kong dollars")),
    "BRL": (("R$",), 2, 250_000, ("real", "reais")),
    "AUD": (("A$", "AU$", "AUD$"), 2, 80_000, ("australian dollar", "australian dollars")),
    "CAD": (("C$", "CA$", "CAD$", "Can$"), 2, 70_000, ("canadian dollar", "canadian dollars")),
    "NZD": (("NZ$", "NZD$"), 2, 90_000, ("new zealand dollar", "new zealand dollars")),
    "INR": (("₹", "Rs.", "Rs"), 2, 4_000_000, ("rupee", "rupees")),
    "JPY": (("円", "JP¥"), 0, 20_000_000, ("yen",)),
    "KRW": (("₩",), 0, 20_000_000, ("won",)),
    "CNY": (("元", "RMB", "CN¥", "RMB¥"), 2, 400_000, ("yuan", "renminbi")),
    "SEK": ((), 2, 500_000, ("swedish krona", "swedish kronor", "kronor")),
    "NOK": ((), 2, 500_000, ("norwegian krone", "norwegian kroner")),
    "DKK": ((), 2, 350_000, ("danish krone", "danish kroner")),
    "PLN": (("zł", "zl"), 2, 200_000, ("zloty", "złoty", "złotych")),
    "CZK": (("Kč",), 2, 1_200_000, ("koruna", "korun")),
    "TRY": (("₺",), 2, 2_000_000, ("turkish lira",)),
    "ZAR": (("ZAR",), 2, 900_000, ("rand",)),
    "MXN": (("MX$", "Mex$", "MXN$"), 2, 900_000, ("mexican peso", "mexican pesos")),
    "RON": (("lei",), 2, 250_000, ("leu", "lei")),
    "HUF": (("Ft",), 0, 20_000_000, ("forint",)),
    "AED": (("د.إ", "Dhs"), 2, 200_000, ("dirham", "dirhams")),
    "SAR": (("﷼",), 2, 200_000, ("riyal", "riyals")),
    "ILS": (("₪",), 2, 200_000, ("shekel", "shekels")),
    "THB": (("฿",), 2, 1_800_000, ("baht",)),
    "MYR": (("RM",), 2, 250_000, ("ringgit",)),
    "IDR": (("Rp",), 0, 800_000_000, ("rupiah",)),
    "PHP": (("₱",), 2, 3_000_000, ("philippine peso", "philippine pesos")),
    "TWD": (("NT$", "NTD$"), 0, 1_800_000, ("taiwan dollar", "new taiwan dollar")),
    # beyond the required set
    "ISK": ((), 0, 8_000_000, ("icelandic krona",)),
    "BGN": (("лв",), 2, 100_000, ("lev", "leva")),
    "RUB": (("₽",), 2, 5_000_000, ("ruble", "rubles")),
    "UAH": (("₴",), 2, 2_000_000, ("hryvnia",)),
    "EGP": ((), 2, 3_000_000, ("egyptian pound", "egyptian pounds")),
    "QAR": ((), 2, 200_000, ("qatari riyal",)),
    "KWD": ((), 3, 20_000, ("kuwaiti dinar",)),
    "NGN": (("₦",), 2, 80_000_000, ("naira",)),
    "KES": (("KSh",), 2, 6_000_000, ("kenyan shilling",)),
    "CLP": ((), 0, 40_000_000, ("chilean peso",)),
    "COP": ((), 0, 200_000_000, ("colombian peso",)),
    "ARS": ((), 2, 50_000_000, ("argentine peso",)),
    "PEN": ((), 2, 200_000, ("sol", "soles")),
    "VND": (("₫",), 0, 1_500_000_000, ("dong",)),
    "PKR": ((), 2, 12_000_000, ("pakistani rupee",)),
}

CURRENCIES: Dict[str, Dict[str, object]] = {
    code: {"symbols": syms, "decimals": dec, "max": float(mx), "names": names}
    for code, (syms, dec, mx, names) in _ROWS.items()
}
KNOWN_CODES = frozenset(CURRENCIES)

_DEFAULT_MAX = 50_000.0
# Codes with a mainstream lower-case spelling in prose ("500 eur"); every other code
# must be UPPER-CASE so "index.php" or "try 5" never reads as a currency.
_CI_CODES = ("GBP", "EUR", "USD", "CHF")


def max_amount(currency: Optional[str]) -> float:
    row = CURRENCIES.get(currency or "")
    return float(row["max"]) if row else _DEFAULT_MAX


def plausible(amount: Optional[float], currency: Optional[str] = None) -> bool:
    """0 <= amount <= the per-currency cap for ONE registration fee."""
    return amount is not None and 0 <= amount <= max_amount(currency)


@dataclass(frozen=True)
class Money:
    amount: float
    currency: Optional[str]                 # ISO code, or None when the text does not say
    high: Optional[float] = None            # upper bound of a range ("€350–€500")
    span: Tuple[int, int] = (0, 0)          # (start, end) of the whole match in the input text


# ── tokens ────────────────────────────────────────────────────────────────────────

# Exact-case multi-char / single-char symbols -> code ("kr" and bare "$" "¥" are resolved later).
_SYMBOL_CODE: Dict[str, Optional[str]] = {}
for _code, (_syms, _d, _m, _n) in _ROWS.items():
    for _s in _syms:
        _SYMBOL_CODE[_s] = _code
_SYMBOL_CODE.update({"$": "USD", "¥": "JPY", "Fr.": "CHF", "kr": None, "kr.": None, "Kr": None, "KR": None, "Kr.": None})
for _bad in ("ZAR", "Fr", "zl"):       # "ZAR" is a code; bare "Fr" / "zl" are too common as word fragments
    _SYMBOL_CODE.pop(_bad, None)

_OTHER_SYMS = sorted(_SYMBOL_CODE, key=len, reverse=True)
# letter-initial symbols need a left boundary so "CLASS$" / "BRs" do not read as S$ / Rs
_WORD_SYMS = [s for s in _OTHER_SYMS if re.match(r"[A-Za-z]", s)]
_PUNCT_SYMS = [s for s in _OTHER_SYMS if not re.match(r"[A-Za-z]", s)]

_CODES_CI = "|".join(_CI_CODES)
_CODES_CS = "|".join(sorted((c for c in KNOWN_CODES if c not in _CI_CODES), key=str))
_WORD_NAMES = r"euros?|pounds?"           # "350 euros", "£" free prose

_SYM_ALT = "|".join(
    [r"(?<![A-Za-z])(?:" + "|".join(re.escape(s) for s in _WORD_SYMS) + r")(?![A-Za-z])" if _WORD_SYMS else r"(?!)"]
    # word-symbols ending in "$" legitimately precede digits/spaces, so the right boundary above is a letter check only
    + [re.escape(s) for s in _PUNCT_SYMS]
)
# Word-symbols that END with "$" (US$ A$ ...) are followed directly by digits; the (?![A-Za-z]) above allows that.

_TOK = (
    r"(?:"
    r"(?<![A-Za-z])(?i:" + _CODES_CI + r")(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:" + _CODES_CS + r")(?![A-Za-z])"
    r"|(?<![A-Za-z])(?i:" + _WORD_NAMES + r")(?![A-Za-z])"
    r"|" + _SYM_ALT +
    r"|元|円"
    r")"
)
# a number with optional thousands groups and an optional 1-2 digit decimal
_NUM = (r"(?<!\d)(?<!\d[.,])(?:\d{1,3}(?:[ '’,.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d)")
_DASH = r"(?:[.,][-–—]{1,2})"            # Swiss "1 200.–" : no decimals
_RANGE_SEP = r"(?:\s*(?:[-–—]|\bto\b)\s*)"

_AMOUNT_RE = re.compile(
    r"(?:(?P<p1>" + _TOK + r")\s*)?(?:(?P<p2>" + _TOK + r")\s*)?"
    r"(?P<n1>" + _NUM + r")(?P<d1>" + _DASH + r")?"
    r"(?:\s*(?P<s1>" + _TOK + r")(?!\s*\d))?"
    r"(?P<rng>" + _RANGE_SEP + r"(?:(?P<q1>" + _TOK + r")\s*)?(?P<n2>" + _NUM + r")(?P<d2>" + _DASH + r")?"
    r"(?:\s*(?P<s2>" + _TOK + r")(?!\s*\d))?)?"
)

_SPACES = str.maketrans({" ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " "})


# ── context evidence (codes / names / symbols in free text) ─────────────────────────

def _name_alternatives() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for code, (_s, _d, _m, names) in _ROWS.items():
        for n in names:
            if n in ("real", "sol", "won", "dong", "rand", "lev", "leu"):
                continue                      # common English words / too ambiguous in prose
            out.append((n, code))
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


_NAMES = _name_alternatives()
_NAME_RE = re.compile(
    r"(?<![A-Za-z])(?i:" + "|".join(re.escape(n) for n, _ in _NAMES) + r")(?![A-Za-z])")
_NAME_CODE = {n.lower(): c for n, c in _NAMES}
_NAME_CODE.update({"kronor": "SEK", "reais": "BRL"})
_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:(?i:" + _CODES_CI + r")|" + _CODES_CS + r")(?![A-Za-z0-9_])")
_CODE_PREFIX_NEAR_DIGIT = re.compile(r"(?<![A-Za-z])(?:(?i:" + _CODES_CI + r")|" + _CODES_CS + r")(?=\d)")
_SYM_ONLY_RE = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(re.escape(s) for s in sorted(
        (s for s in _SYMBOL_CODE if s not in ("$", "¥", "kr", "kr.", "Kr", "KR", "Kr.", "Fr.") and _SYMBOL_CODE[s]
         and re.match(r"[A-Za-z]", s) and s not in ("Rs",)), key=len, reverse=True)) + r")(?![A-Za-z])"
    r"|" + "|".join(re.escape(s) for s in sorted(
        (s for s in _SYMBOL_CODE if _SYMBOL_CODE[s] and not re.match(r"[A-Za-z]", s) and s not in ("$", "¥")),
        key=len, reverse=True)) + r"|元|円|Fr\.(?=\s*\d)")
_BARE_DOLLAR_RE = re.compile(r"(?<![A-Za-z$])\$")
_YEN_RE = re.compile(r"¥")
_URL_TLD = {
    "uk": "GBP", "ie": "EUR", "de": "EUR", "fr": "EUR", "it": "EUR", "es": "EUR", "nl": "EUR", "be": "EUR",
    "at": "EUR", "fi": "EUR", "pt": "EUR", "gr": "EUR", "lu": "EUR", "sk": "EUR", "si": "EUR", "ee": "EUR",
    "lv": "EUR", "lt": "EUR", "mt": "EUR", "cy": "EUR", "hr": "EUR",
    "ch": "CHF", "li": "CHF", "au": "AUD", "ca": "CAD", "nz": "NZD", "sg": "SGD", "hk": "HKD", "jp": "JPY",
    "kr": "KRW", "in": "INR", "se": "SEK", "no": "NOK", "dk": "DKK", "pl": "PLN", "cz": "CZK", "hu": "HUF",
    "ro": "RON", "tr": "TRY", "za": "ZAR", "mx": "MXN", "br": "BRL", "il": "ILS", "th": "THB", "my": "MYR",
    "id": "IDR", "ph": "PHP", "tw": "TWD", "cn": "CNY", "ae": "AED", "sa": "SAR", "is": "ISK", "bg": "BGN",
    "ua": "UAH", "eg": "EGP", "ng": "NGN", "ke": "KES", "cl": "CLP", "co": "COP", "ar": "ARS", "pe": "PEN",
    "vn": "VND", "pk": "PKR", "qa": "QAR", "kw": "KWD",
}
_DOLLARS = ("AUD", "CAD", "NZD", "SGD", "HKD", "MXN", "TWD")


def _evidence(text: str) -> List[Tuple[int, int, str]]:
    """(class, position, code) for every explicit currency mention in `text`.
    class 0 = ISO code, 1 = currency name, 2 = unambiguous symbol, 3 = bare '$' / '¥'."""
    hits: List[Tuple[int, int, str]] = []
    for m in _CODE_RE.finditer(text):
        hits.append((0, m.start(), m.group(0).upper()))
    for m in _CODE_PREFIX_NEAR_DIGIT.finditer(text):         # "EUR1500"
        hits.append((0, m.start(), m.group(0).upper()))
    for m in _NAME_RE.finditer(text):
        hits.append((1, m.start(), _NAME_CODE[m.group(0).lower()]))
    for m in _SYM_ONLY_RE.finditer(text):
        code = _SYMBOL_CODE.get(m.group(0)) or {"元": "CNY", "円": "JPY"}.get(m.group(0)) or ("CHF" if m.group(0).startswith("Fr") else None)
        if code:
            hits.append((2, m.start(), code))
    explicit = {h[2] for h in hits}
    for m in _BARE_DOLLAR_RE.finditer(text):
        hits.append((3, m.start(), "USD"))
    for m in _YEN_RE.finditer(text):
        hits.append((3, m.start(), "CNY" if "CNY" in explicit else "JPY"))
    return hits


def _tld_currency(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    m = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^/@]*@)?([^/:?#]+)", url.strip(), re.I)
    if not m:
        return None
    return _URL_TLD.get(m.group(1).lower().rsplit(".", 1)[-1])


def detect_currency(context: str, url: Optional[str] = None) -> Optional[str]:
    """Currency EVIDENCED by the text (heading, table, page chunk): an ISO code beats a
    currency name beats a symbol beats a bare '$' / '¥'; the earliest mention wins within
    the best class. When the text says nothing, fall back to the URL's country TLD
    (".uk" -> GBP). NEVER defaults: no evidence -> None."""
    ctx = (context or "").translate(_SPACES)
    hits = _evidence(ctx) if ctx else []
    if hits:
        dollars = {c for k, _p, c in hits if k < 3 and c in _DOLLARS}
        usd_explicit = any(k < 3 and c == "USD" for k, _p, c in hits)
        cleaned = []
        for k, p, c in hits:
            if k == 3 and c == "USD" and dollars and not usd_explicit:
                c = sorted(dollars)[0] if len(dollars) == 1 else None
                if c is None:
                    continue
            cleaned.append((k, p, c))
        if cleaned:
            cleaned.sort(key=lambda h: (h[0], h[1]))
            return cleaned[0][2]
    return _tld_currency(url)


def normalize_currency(raw) -> Optional[str]:
    """ISO code, symbol, or currency name -> ISO code in KNOWN_CODES; anything else
    (None, '', 'unknown', 'N/A', 'kr') -> None. Never defaults."""
    if raw is None:
        return None
    s = str(raw).strip().translate(_SPACES)
    if not s:
        return None
    if s in _SYMBOL_CODE:
        return _SYMBOL_CODE[s]
    u = s.upper()
    if u in KNOWN_CODES:
        return u
    if u.rstrip(".$") in KNOWN_CODES and u.endswith("$"):
        return u.rstrip("$")
    if s in ("元", "円"):
        return "CNY" if s == "元" else "JPY"
    if len(s) <= 32:
        return detect_currency(s)
    return None


def prompt_symbol_table() -> str:
    """Symbol legend for LLM / vision prompts, generated from the table above."""
    pairs = ["£=GBP", "€=EUR", "plain $=USD", "US$=USD", "A$=AUD", "C$=CAD", "NZ$=NZD", "S$=SGD", "HK$=HKD",
             "R$=BRL", "MX$=MXN", "NT$=TWD", "¥ or 円=JPY (¥ with RMB/元=CNY)", "₩=KRW", "₹=INR", "₺=TRY", "₪=ILS",
             "zł=PLN", "Kč=CZK", "Ft=HUF", "lei=RON", "RM=MYR", "Rp=IDR", "฿=THB", "₱=PHP", "Fr./CHF=CHF",
             "kr=SEK/NOK/DKK only if stated"]
    return ", ".join(pairs)


# ── number parsing ───────────────────────────────────────────────────────────────

def parse_number(raw: str, currency: Optional[str] = None, dash: bool = False) -> Optional[float]:
    """Parse the numeric part of an amount per the decimal rule in the module docstring."""
    s = (raw or "").strip().translate(_SPACES)
    if not s or not re.fullmatch(r"\d[\d ',’.]*", s):
        return None
    s = re.sub(r"[ '’]", "", s)                        # always thousands marks
    if dash:
        s = re.sub(r"[.,]", "", s)
        return float(s) if s else None
    seps = [(i, ch) for i, ch in enumerate(s) if ch in ".,"]
    if not seps:
        return float(s)
    last_i, last_ch = seps[-1]
    tail = s[last_i + 1:]
    kinds = {ch for _i, ch in seps}
    if len(kinds) == 2:                                # both present: the last one is the decimal mark
        if len(tail) <= 2:
            return float(s[:last_i].replace(".", "").replace(",", "") + "." + tail)
        return float(s.replace(".", "").replace(",", ""))
    if len(seps) > 1:                                  # repeated same mark: thousands (1.500.000)
        return float(s.replace(".", "").replace(",", ""))
    if len(tail) == 3:                                 # single mark + 3 digits: thousands (also for 0-decimal currencies)
        return float(s.replace(".", "").replace(",", ""))
    if len(tail) in (1, 2):
        return float(s[:last_i] + "." + tail)
    return None


# ── amount scanning ──────────────────────────────────────────────────────────────

def _resolve_token(tok: Optional[str], ctx_evidence: List[Tuple[int, int, str]]) -> Tuple[bool, Optional[str]]:
    """(token_present, currency) for one matched currency token."""
    if not tok:
        return False, None
    t = tok.translate(_SPACES)
    ev = {c for k, _p, c in ctx_evidence if k < 3}
    if t in ("元",):
        return True, "CNY"
    if t == "円":
        return True, "JPY"
    if t == "$":
        others = sorted(c for c in ev if c in _DOLLARS)
        if "USD" in ev or not others:
            return True, "USD"
        return True, others[0] if len(others) == 1 else None
    if t == "¥":
        return True, "CNY" if "CNY" in ev else "JPY"
    if t in ("kr", "kr.", "Kr", "KR", "Kr."):
        kr = sorted(c for c in ev if c in ("SEK", "NOK", "DKK"))
        return True, kr[0] if len(kr) == 1 else None
    if t in _SYMBOL_CODE:
        return True, _SYMBOL_CODE[t]
    if t.upper() in KNOWN_CODES:
        return True, t.upper()
    if t.lower() in ("euro", "euros"):
        return True, "EUR"
    if t.lower() in ("pound", "pounds"):
        return True, "GBP"
    return True, None


_COUNTER_BEFORE_RE = re.compile(
    r"\b(?:module|day|part|session|week|workshop|lecture|step|stage|level|class|year|option|package|"
    r"tier|category|group|room|track|course|hour|number|no\.?|nr\.?|#)\s*$", re.I)


def _looks_like_year(raw: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20|21)\d\d", raw.strip()))


def _scan(text: str, context: Optional[str], require_currency: bool) -> Iterator[Money]:
    if not text:
        return
    norm = text.translate(_SPACES)
    ctx_evidence = _evidence(norm + " " + (context or "").translate(_SPACES))
    for m in _AMOUNT_RE.finditer(norm):
        toks = [m.group(g) for g in ("p1", "p2", "s1")] + ([m.group("q1"), m.group("s2")] if m.group("rng") else [])
        resolved = [_resolve_token(t, ctx_evidence) for t in toks if t]
        present = any(p for p, _c in resolved)
        codes = [c for _p, c in resolved if c]
        # a code token beats a symbol token ("USD $350"); otherwise first resolved wins
        cur: Optional[str] = None
        for t in toks:
            if t and t.translate(_SPACES).upper() in KNOWN_CODES:
                cur = t.translate(_SPACES).upper()
                break
        if cur is None and codes:
            cur = codes[0]
        if require_currency and not present:
            continue
        n1 = m.group("n1")
        start = m.start()
        cut_applied = False
        prefix_text = norm[:m.start("n1")]
        # A SUFFIX code ("Module 3 450 EUR") is no proof that "3 450" is one number when a
        # counter word ("Module", "Day", "Part", ...) introduces the first group; a prefix
        # marker ("EUR 1 200") or a bare cell ("1 200,00 €") keeps its thousands reading.
        suffix_only = bool(m.group("s1")) and not (m.group("p1") or m.group("p2"))
        counter_label = suffix_only and bool(_COUNTER_BEFORE_RE.search(prefix_text))
        if (not present or counter_label) and " " in n1 and re.search(r"[A-Za-z]", prefix_text):
            # No currency marker AND the number sits in prose: a space is NOT a thousands mark
            # ("Day 1 350" is 350, not 1350). Keep only the last group. A bare number that IS
            # the cell ("1 200,00", "2 500") keeps space thousands. (X1, 2026-10-27)
            cut = n1.rindex(" ")
            start = m.start("n1") + cut + 1
            n1 = n1[cut + 1:]
            cut_applied = True
        amount = parse_number(n1, cur, dash=bool(m.group("d1")))
        if amount is None:
            continue
        high = None
        if m.group("rng"):
            n2 = m.group("n2")
            own_tok = bool(m.group("q1") or m.group("s2"))
            h = parse_number(n2, cur, dash=bool(m.group("d2")))
            if h is not None and h > amount and (own_tok or not _looks_like_year(n2)):
                high = h
        end = m.end() if high is not None else (m.end("s1") if m.group("s1") else m.end("d1") if m.group("d1") else m.end("n1"))
        yield Money(amount=amount, currency=cur, high=high, span=(start if (not present or cut_applied) else m.start(), end))


def find_amounts(text: str, context: Optional[str] = None, require_currency: bool = True) -> List[Money]:
    """Every amount in `text` that carries a currency token (symbol or code, prefix or
    suffix). `require_currency=False` also returns bare numbers (currency None)."""
    return list(_scan(text, context, require_currency))


def parse_amount(text: str, context: Optional[str] = None) -> Optional[Money]:
    """First amount in `text` (a cell or short line). A currency-bearing amount wins over
    an earlier bare number. "Free" / "TBC" / no digits -> None. A "kr" or other
    unresolvable symbol yields Money(amount, currency=None)."""
    found = list(_scan(text, context, require_currency=False))
    if not found:
        return None
    for mny in found:
        if mny.currency:
            return mny
    return found[0]
