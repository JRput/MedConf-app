"""Small shared helpers: find fee-ish PDF/DOCX links and extract their text.

Text-layer only (pypdf / zipfile). Scanned-image PDFs yield no text and are
reported as such, never OCR'd here.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote

PDF_MAX_PAGES = 20
PDF_MAX_BYTES = 8_000_000

_DOC_HREF_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\']+?\.(?:pdf|docx))(?:[?#][^"\']*)?["\'][^>]*>(.{0,400}?)</a>', re.I | re.S)
FEE_LINK_RE = re.compile(r"fee|price|pricing|cost|registration|brochure|rates?\b|tariff", re.I)
# Documents that mention a fee but are not attendee fee schedules.
NEG_LINK_RE = re.compile(
    r"endorse|application|abstract|sponsor|exhibit|terms|conditions|privacy|"
    r"cancellation|policy|poster|call[-_ ]for|guidelines|visa|accommodation|travel", re.I)


def find_fee_documents(html: str, base_url: str, limit: int = 3) -> list[tuple[str, str]]:
    """PDF/DOCX links whose href or anchor text looks like a fee document."""
    out: list[tuple[str, str]] = []
    seen: set = set()
    for m in _DOC_HREF_RE.finditer(html or ""):
        href = m.group(1).strip()
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        url = urljoin(base_url, href.replace("&amp;", "&"))
        if urlparse(url).scheme not in ("http", "https") or url in seen:
            continue
        name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        hay = f"{name} {text}"
        if not FEE_LINK_RE.search(hay) or NEG_LINK_RE.search(hay):
            continue
        seen.add(url)
        out.append((url, text[:80] or name))
        if len(out) >= limit:
            break
    return out


def _norm(text: str) -> str:
    return re.sub(r"[ \t\r\f\v\xa0]+", " ", text or "").strip()


def pdf_to_text(data: bytes, max_pages: int = PDF_MAX_PAGES) -> str:
    """Text layer of the first `max_pages` pages, one line per source line.
    Empty string for scanned/unreadable PDFs."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for pg in reader.pages[:max_pages]:
            try:
                pages.append(pg.extract_text() or "")
            except Exception:
                continue
    except Exception:
        return ""
    lines = [_norm(l) for l in "\n".join(pages).splitlines()]
    return "\n".join(l for l in lines if l)


def docx_to_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf8", "ignore")
    except Exception:
        return ""
    import html as _h
    xml = re.sub(r"</w:p>\s*</w:tc>", " | ", xml)  # cell boundary -> "label | price"
    xml = re.sub(r"</w:tc>", " | ", xml)
    xml = re.sub(r"</w:tr>|</w:p>|<w:br\s*/>", "\n", xml)
    xml = re.sub(r"<w:tab\s*/>", " ", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    lines = [_norm(l) for l in _h.unescape(xml).splitlines()]
    return "\n".join(l.rstrip(" |") for l in lines if l.strip(" |"))


def document_to_text(data: bytes, url: str) -> str:
    if urlparse(url).path.lower().endswith(".docx") or data[:2] == b"PK":
        return docx_to_text(data)
    return pdf_to_text(data)
