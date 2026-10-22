"""Description fixer — extract 30-50 word summary from source page.

Strategy:
  1. Strip site chrome (nav/header/footer/cookie/breadcrumb) from the HTML when
     available, then collect clean candidates: meta/og description first, then
     <main>/<article> paragraphs. Without HTML, fall back to line/sentence
     candidates from the flattened page text.
  2. LLM: summarise ONLY the cleaned candidate text.
  3. Validate every candidate (scraped or LLM) with _is_clean(); on rejection
     write nothing (None) — null is better than chrome (HQ LESSONS #4).
"""

from __future__ import annotations
import html as _html
import logging
import re
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_NAV_LEAK_RE = re.compile(
    r"(T \+44|W rcog\.org\.uk|Registered charity|Disclaimer:|Cookies:|"
    r"Join the conversation|Privacy Policy|Skip to main content|Log in / Register|"
    r"Limitations of use|@RC[A-Za-z]+|MyRCR|Copyright)",
)
# Mirrors remediator/audit.py check_description's nav-leak phrases.
_AUDIT_PHRASES = ("register now", "login", "menu", "cookie policy",
                  "javascript is required")
_CHROME_RE = re.compile(
    r"become a member|contact us|skip to|log ?in|sign ?in|sign ?up|my account|"
    r"cookies?\b|consent|privacy|terms (?:and|&|of)|accept all|"
    r"all rights reserved|subscribe to|newsletter|follow us|site ?map|"
    r"what we do|sustainability|accessibility statement|back to top|read more",
    re.I,
)
_STRONG_CHROME_RE = re.compile(
    r"become a member|contact us|skip to|back to (?:the )?(?:event|home|top|list)|"
    r"find out more|continue back|log ?in\b|sign ?in\b|my account", re.I)
_BREADCRUMB_RE = re.compile(r"\S\s*(?:>|›|»|/)\s*\S+\s*(?:>|›|»)\s*\S")
_FIRST_SENT_RE = re.compile(r"cookie|privacy|terms", re.I)

_STRIP_BLOCK_RE = re.compile(
    r"(?is)<(script|style|svg|noscript|nav|header|footer|aside|form|template|"
    r"iframe|button|select)\b.*?</\1\s*>")
_STRIP_CLASS_RE = re.compile(
    r"""(?is)<(div|section|ul|ol|p|span)\b[^>]*(?:class|id)=["'][^"']*"""
    r"""(?:cookie|consent|gdpr|breadcrumb|menu|navbar|nav-|sidebar|banner|"""
    r"""skip-link|social|share)[^"']*["'][^>]*>.*?</\1\s*>""")

_OVERVIEW_MARKERS = (
    "overview", "about this", "about the", "summary", "event description",
    "event summary", "key information",
)


def _meta(html: str, name: str) -> Optional[str]:
    for rx in (rf"""<meta\b[^>]*(?:property|name)=["']{name}["'][^>]*content=["']([^"']*)""",
               rf"""<meta\b[^>]*content=["']([^"']*)["'][^>]*(?:property|name)=["']{name}["']"""):
        m = re.search(rx, html or "", re.I)
        if m:
            return _norm(_html.unescape(m.group(1))) or None
    return None


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _strip_tags(h: str) -> str:
    return _norm(_html.unescape(re.sub(r"<[^>]+>", " ", h)))


def _is_clean(c: str) -> bool:
    """True only for a genuine prose candidate (no chrome, nav or cookie text)."""
    c = _norm(c)
    if not c or len(c) < 50 or len(c) > 700:
        return False
    low = c.lower()
    if any(p in low for p in _AUDIT_PHRASES) or _NAV_LEAK_RE.search(c):
        return False
    if _BREADCRUMB_RE.search(c) or " > " in c:
        return False
    if _STRONG_CHROME_RE.search(c):
        return False
    first = re.split(r"(?<=[.!?])\s", c, maxsplit=1)[0]
    if _FIRST_SENT_RE.search(first):
        return False
    if len(_CHROME_RE.findall(c)) >= 2:
        return False
    words = c.split()
    if len(words) < 10:
        return False
    # Mostly capitalised link text (nav strips) is not prose.
    alpha_words = [w for w in words if w[:1].isalpha()]
    if alpha_words and sum(1 for w in alpha_words if w[0].isupper()) / len(alpha_words) > 0.5:
        return False
    alphas = [ch for ch in c if ch.isalpha()]
    if alphas and sum(1 for ch in alphas if ch.isupper()) / len(alphas) > 0.5:
        return False
    # Prose needs sentence punctuation.
    return bool(re.search(r"[.!?](\s|$)", c))


def _html_candidates(html: str) -> List[str]:
    """Meta description first, then paragraphs of <main>/<article> after chrome strip."""
    out: List[str] = []
    for name in ("description", "og:description"):
        m = _meta(html, name)
        if m:
            out.append(m)
    body = _STRIP_BLOCK_RE.sub(" ", html or "")
    body = _STRIP_CLASS_RE.sub(" ", body)
    for tag in ("main", "article"):
        m = re.search(rf"(?is)<{tag}\b[^>]*>(.*)</{tag}\s*>", body)
        if m:
            body = m.group(1)
            break
    for pm in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p\s*>", body):
        t = _strip_tags(pm.group(1))
        if t:
            out.append(t)
    return out


def _text_candidates(text: str) -> List[str]:
    """Candidates from flattened page text: lines, else sentence groups."""
    lines = [_norm(l) for l in re.split(r"\n+", text or "") if _norm(l)]
    if len(lines) < 2:
        sents = re.split(r"(?<=[.!?])\s+", _norm(text))
        lines = [" ".join(sents[i:i + 2]) for i in range(0, len(sents), 2)]
    return lines


def _candidates(row: dict, page_text: str) -> List[str]:
    html = row.get("_page_html") or ""
    cands = _html_candidates(html) if html else []
    cands += _text_candidates(page_text)
    return [c for c in cands if _is_clean(c)]


def fix_description(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[str], Optional[str]]:
    rid = row.get("id")
    clean = _candidates(row, page_text)
    if not clean:
        logger.info(f"description: no clean candidate for {rid}")
        return None, None

    # Meta/first clean paragraph is the heuristic answer; the LLM only sees
    # cleaned body text and its output is re-validated.
    chunk = " ".join(clean[:6])[:2500]
    title = row.get("conference_name") or ""
    prompt = f"""Summarise this medical event in 30-50 words, using ONLY the supplied text.
Plain prose, no markdown, no headings.

EVENT TITLE: {title}

PAGE TEXT:
{chunk}

Respond with ONLY the summary, nothing else."""

    raw = llm_call(prompt)
    if raw:
        candidate = _norm(raw.strip().strip("`"))
        if _is_clean(candidate):
            return candidate, "llm_overview"
    fallback = clean[0]
    if len(fallback) > 320:
        sents = re.split(r"(?<=[.!?])\s+", fallback)
        fallback = sents[0] if len(sents[0]) >= 50 else fallback[:320].rsplit(" ", 1)[0]
    if _is_clean(fallback):
        return fallback, "heuristic_overview"
    logger.info(f"description: no clean candidate for {rid}")
    return None, None
