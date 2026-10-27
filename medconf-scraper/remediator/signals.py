"""Pure page-text signals shared by the audit gate and the pricing fixer.

Kept dependency-free so `remediator.audit` and `remediator.fixers.pricing`
can both import it without a cycle.
"""
from __future__ import annotations
import re

FREE_EVENT_RE = re.compile(r"(?:free\s+(?:to\s+attend|of\s+charge|event|admission)|"
                           r"complimentary|no\s+(?:cost|charge|fee))")


# Words that mark an amount as a penalty / side charge rather than a fee.
NON_FEE_CONTEXT_RE = re.compile(
    r"cancell?ation|no[- ]?show|non[- ]?attendance|do\s+not\s+attend|"
    r"charged\s+a\s+fee\s+of|penalt|parking|deposit|late[- ]payment|"
    r"admin(?:istration|istrative)?\s+(?:charge|fee)|refund", re.I)

_AMOUNT_RE = re.compile(
    r"(?:[£$€]|(?<![A-Za-z])(?:EUR|USD|GBP|CHF|SGD|HKD|BRL|AUD|CAD))"
    r"[\s\u00a0]*(\d[\d,]*(?:\.\d+)?)", re.I)


def price_text_signal(page_text: str) -> bool:
    """True when the page shows non-zero currency amounts (symbol or ISO code)
    that look like fees: zero amounts and penalty/side charges (cancellation,
    no-show, parking, deposit, refund...) in the preceding 40 chars are ignored.
    Pure; shared with the audit and the new-source coverage checks."""
    text = page_text or ""
    for m in _AMOUNT_RE.finditer(text):
        try:
            if float(m.group(1).replace(",", "")) == 0:
                continue
        except ValueError:
            continue
        window = text[max(0, m.start() - 40): m.start()]
        cut = max(window.rfind(". "), window.rfind("\n"), window.rfind("\t"))
        if cut >= 0:
            window = window[cut + 1:]  # lookback never crosses a sentence/line/cell
        if NON_FEE_CONTEXT_RE.search(window):
            continue
        return True
    return False


# Words that mean a "free" phrase is describing ONE fee category (a table row),
# not the whole event.
_CATEGORY_WORDS_RE = re.compile(
    r"\b(?:press|media|members?|non[- ]?members?|students?|trainees?|nurses?|"
    r"industry|academia|concessions?|retired|early[- ]?bird|late|standard|"
    r"speakers?|faculty|exhibitors?|sponsors?|representatives?|category|"
    r"fees?|rates?|prices?)\b", re.I)
_EVENT_WORDS_RE = re.compile(
    r"\b(?:registration|register|attend|attendance|event|webinar|course|"
    r"meeting|admission|delegates?)\b", re.I)
_WINDOW = 120


def free_phrase_context(page_text: str, free_re: "re.Pattern[str]") -> "str | None":
    """Return the matched line when `free_re` matches in a context that really
    describes the whole event being free; else None.

    Rejects: table rows (tab/pipe-separated cells), lines naming other fee
    categories, and phrases with no event/registration word within ~120 chars.
    """
    text = page_text or ""
    for m in free_re.finditer(text):
        ls = text.rfind("\n", 0, m.start()) + 1
        le = text.find("\n", m.end())
        le = len(text) if le < 0 else le
        line = text[ls:le]
        if "\t" in line.strip() or "|" in line:
            continue
        rest = line[: m.start() - ls] + " " + line[m.end() - ls:]
        if _CATEGORY_WORDS_RE.search(rest):
            continue
        around = text[max(0, m.start() - _WINDOW): m.start()] + " " + text[m.end(): m.end() + _WINDOW]
        if not (_EVENT_WORDS_RE.search(around) or _EVENT_WORDS_RE.search(m.group(0))):
            continue
        return line.strip()
    return None
