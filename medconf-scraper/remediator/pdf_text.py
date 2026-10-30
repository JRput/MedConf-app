"""Small shared helpers: find fee-ish PDF/DOCX links and extract their text.

Text-layer only (pypdf / zipfile). Scanned-image PDFs yield no text and are
reported as such, never OCR'd here.
"""
from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote

logger = logging.getLogger(__name__)

PDF_MAX_PAGES = 20
PDF_MAX_BYTES = 8_000_000

_DOC_HREF_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\']+?\.(?:pdf|docx))(?:[?#][^"\']*)?["\'][^>]*>(.{0,400}?)</a>', re.I | re.S)
FEE_LINK_RE = re.compile(r"fee|price|pricing|cost|registration|brochure|rates?\b|tariff", re.I)
# Documents that mention a fee but are not attendee fee schedules.
NEG_LINK_RE = re.compile(
    r"endorse|application|abstract|sponsor|exhibit|terms|conditions|privacy|"
    r"cancellation|policy|poster|call[-_ ]for|guidelines|visa|accommodation|travel|"
    # Site-wide documents that are not one event's attendee fees (2026-10-30 incident).
    r"\btraining|cost[-_ ]of|\bmembership|\bsubscription|\bexam(?:s|ination)?\b|medicare|"
    r"fee[-_ ]schedule|\breport|\bminutes\b|\bagenda\b|\bbylaws\b|\bhandbook|"
    r"\bcurriculum|\bsyllabus|\bnewsletter|annual[-_ ]report", re.I)
# Text-level negative: the document itself reads as a membership/training/exam price list.
NEG_TEXT_RE = re.compile(
    r"membership fee|subscription|cost of training|examination fee|MRCPsych|CPD subscription", re.I)
_YEAR20_RE = re.compile(r"(?<![0-9])(20\d\d)(?![0-9])")


def _row_start_year(row) -> Optional[int]:
    y = str((row or {}).get("start_date") or "")[:4]
    return int(y) if y.isdigit() and y.startswith("20") else None


def document_gate(url: str, anchor_text: str, row: Optional[dict]) -> tuple:
    """Pure identity/negative check on a candidate document link. (ok, reason)."""
    name = unquote(urlparse(url or "").path.rsplit("/", 1)[-1])
    hay = f"{name} {anchor_text or ''}"
    m = NEG_LINK_RE.search(hay)
    if m:
        return False, f"site_wide_document ({m.group(0).strip()})"
    if row:
        from extractors.discovery import url_edition_reason
        why = url_edition_reason(row, url)
        if why:
            return False, f"prior_edition: {why}"
        sy = _row_start_year(row)
        if sy:
            for y in _YEAR20_RE.findall(name):
                if int(y) < sy:
                    return False, f"prior_edition: name carries {y} < {sy}"
    return True, "ok"


def document_text_gate(text: str, row: Optional[dict]) -> tuple:
    """Identity check on a fetched document's first 2,000 characters. (ok, reason)."""
    head = (text or "")[:2000]
    if NEG_TEXT_RE.search(head):
        return False, "reads as membership/training/exam document"
    if row:
        from extractors.discovery import _foreign_year, row_years
        fy = _foreign_year(head, row_years(row), row.get("start_date"))
        if fy:
            return False, f"foreign_year {fy}"
    return True, "ok"


def find_fee_documents(html: str, base_url: str, limit: int = 3,
                       row: Optional[dict] = None) -> list[tuple[str, str]]:
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
        if not document_gate(url, text, row)[0]:
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


_PDF_CHILD = r"""
import io, sys, logging
logging.getLogger("pypdf").setLevel(logging.CRITICAL)
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
except Exception:
    pass
data = sys.stdin.buffer.read()
out = []
failed = 0
try:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    for pg in reader.pages[:int(sys.argv[1])]:
        try:
            out.append(pg.extract_text() or "")
        except Exception:
            failed += 1
            continue
except Exception as e:
    sys.stderr.write("pdf_child_error:" + type(e).__name__)
    sys.exit(3)
if failed:
    sys.stderr.write("pdf_child_pages_failed:%d" % failed)
sys.stdout.write("\n".join(out)[:2000000])
"""


_MARKER_RE = re.compile(r"pdf_child_(?:error|pages_failed):[A-Za-z0-9_]+")


def _stderr_marker(stderr: bytes) -> str:
    """Our marker from anywhere in the child's stderr, else its last 200 chars.
    Callers log it with !r: stderr can carry PDF-influenced text."""
    text = (stderr or b"").decode("utf-8", "ignore")
    m = _MARKER_RE.search(text)
    return m.group(0) if m else text[-200:]


def pdf_to_text_isolated(data: bytes, max_pages: int = PDF_MAX_PAGES, timeout: float = 20) -> str:
    """Safe-fetch mode: parse the PDF in a child process (bytes on stdin,
    hard timeout, address-space limit) so a parser hang or memory bug cannot
    take the job down. Same output shape as pdf_to_text; "" on any failure."""
    import subprocess
    import sys
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PDF_CHILD, str(int(max_pages))],
            input=data, capture_output=True, timeout=timeout, check=False,
            env={"PATH": os.environ.get("PATH", "")})  # no secrets in the child
    except Exception as e:
        logger.warning(f"pdf_text: isolated parse failed ({type(e).__name__}, {len(data)} bytes)")
        return ""
    if proc.returncode != 0:
        marker = _stderr_marker(proc.stderr)
        logger.warning(f"pdf_text: isolated parse exited {proc.returncode} ({len(data)} bytes; stderr: {marker!r})")
        return ""
    raw = proc.stdout.decode("utf-8", "ignore")
    lines = [_norm(l) for l in raw.splitlines()]
    text = "\n".join(l for l in lines if l)
    if not text:
        marker = _stderr_marker(proc.stderr)
        logger.warning(f"pdf_text: isolated parse produced no text ({len(data)} bytes; stderr: {marker!r})")
    return text


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
