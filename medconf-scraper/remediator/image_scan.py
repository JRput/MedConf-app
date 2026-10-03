"""Locate <img> elements that plausibly carry a fee table.

Shared by the audit (detection only, never calls vision) and the explorer
(selection for the vision pass). Pure functions, no network.

Why this exists (2026-10-04, ISUOG row 2492): the fee table was an inline
base64 PNG under a bare "Registration" heading, with no currency text on the
page. The old money-word window never fired and the audit saw nothing.
"""
from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin

# Heading-ish label that introduces a fee block.
FEE_LABEL_RE = re.compile(
    r"\b(?:fees?|registration|pric(?:e|es|ing)|cost|costs|rates?|tariff|tickets?)\b", re.I)
# Heading-ish elements. h1-h4 plus inline labels people use as headings.
_HEADING_RE = re.compile(
    r"<(h[1-4]|strong|b|dt|th|label)\b[^>]*>(.*?)</\1\s*>", re.I | re.S)
# "Registration fee:" / "Fees:" as plain text label.
_TEXT_LABEL_RE = re.compile(
    r"(?:registration\s+fees?|fees?|prices?|pricing|costs?)\s*:", re.I)
_MONEY_NEAR_RE = re.compile(
    r"(?:£|€|\$|₩|\bfees?\b|\bprices?\b|\bregistration\b|\bdelegate\b|\btariff\b|\brates?\b|\bcost\b)",
    re.I)
IMG_SKIP_RE = re.compile(
    r"logo|/brand/|icon|favicon|\.svg|sponsor|partner|banner|hero|avatar|profile|"
    r"headshot|thumb|social|twitter|facebook|linkedin|youtube|instagram|\.gif$|"
    r"1x1|pixel|spacer|badge|award|accredit",
    re.I,
)
_ALT_SRC_FEE_RE = re.compile(r"fee|price|rate|regist", re.I)
_DATA_RE = re.compile(r"data:image/([a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", re.I)
_DATA_OK_TYPES = {"png", "jpeg", "jpg", "webp"}  # vision-compatible rasters

MIN_DIM_PX = 120          # skip when the largest known dimension is below this
SUBSTANTIAL_PX = 300      # audit: "substantial" by declared width/height
SUBSTANTIAL_DATA_BYTES = 5 * 1024
HEADING_REACH_CHARS = 2500  # image must sit within this much markup after the label
WINDOW = 600


@dataclass
class ImageCandidate:
    src: str                      # absolute URL, or the unchanged data: URI
    is_data: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    data_bytes: int = 0
    heading: Optional[str] = None  # fee label this image sits under
    money_nearby: bool = False
    alt_src_fee: bool = False
    skipped: Optional[str] = None  # reason, if filtered out
    rules: List[str] = field(default_factory=list)

    @property
    def area(self) -> int:
        if self.width and self.height:
            return self.width * self.height
        return (self.width or self.height or 0) * 100

    @property
    def substantial(self) -> bool:
        if self.is_data and self.data_bytes > SUBSTANTIAL_DATA_BYTES:
            return True
        if (self.width or 0) >= SUBSTANTIAL_PX or (self.height or 0) >= SUBSTANTIAL_PX:
            return True
        return self.alt_src_fee

    def label(self) -> str:
        return f"data-uri({self.data_bytes}B)" if self.is_data else self.src[:160]


def _attr(tag: str, name: str) -> Optional[str]:
    m = re.search(rf'\b{name}\s*=\s*["\']?([^"\'\s>]+)', tag, re.I)
    return m.group(1) if m else None


def _int(v: Optional[str]) -> Optional[int]:
    if not v:
        return None
    m = re.match(r"(\d+)", v.strip())
    return int(m.group(1)) if m else None


def _png_dims(raw: bytes) -> Optional[tuple]:
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    return None


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def scan_images(html: str, base_url: str) -> List[ImageCandidate]:
    """Return every <img> as an ImageCandidate with fee-context facts filled
    in (candidates that fail the type/size/skip filters carry `skipped`)."""
    if not html:
        return []
    # Mask base64 payloads so offsets/windows stay small and money regexes
    # never run over megabytes of base64.
    payloads: List[str] = []

    def _mask(m):
        payloads.append(m.group(0))
        return f"data:image/{m.group(1)};base64,@@{len(payloads) - 1}@@"

    masked = _DATA_RE.sub(_mask, html)
    heads = []
    for m in _HEADING_RE.finditer(masked):
        txt = _strip_tags(m.group(2))
        if txt and FEE_LABEL_RE.search(txt) and len(txt) <= 120:
            heads.append((m.start(), m.end(), txt))
        elif txt:
            heads.append((m.start(), m.end(), None))   # non-fee heading: breaks the block
    for m in _TEXT_LABEL_RE.finditer(masked):
        heads.append((m.start(), m.end(), m.group(0).strip()))
    heads.sort()

    out: List[ImageCandidate] = []
    for m in re.finditer(r"<img\b[^>]*>", masked, re.I):
        tag = m.group(0)
        src = (_attr(tag, "src") or _attr(tag, "data-src") or "").strip()
        if not src:
            continue
        c = ImageCandidate(src=src)
        tag_wo_src = tag.replace(src, "")
        dm = re.match(r"data:image/([a-z0-9.+-]+);base64,@@(\d+)@@", src, re.I)
        if dm:
            c.is_data = True
            full = payloads[int(dm.group(2))]
            c.src = re.sub(r"\s+", "", full)          # pass through unchanged (minus wrapping whitespace)
            b64 = c.src.split("base64,", 1)[1]
            c.data_bytes = len(b64) * 3 // 4
            if dm.group(1).lower() not in _DATA_OK_TYPES:
                c.skipped = f"data type {dm.group(1)} unsupported"
            else:
                try:
                    d = _png_dims(base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4)))
                    if d:
                        c.width, c.height = d
                except Exception:
                    pass
            skip_target = tag_wo_src
        else:
            if src.startswith("//"):
                src = "https:" + src
            elif not src.lower().startswith("http"):
                src = urljoin(base_url, src)
            c.src = src
            skip_target = src + " " + tag_wo_src
        c.width = _int(_attr(tag, "width")) or c.width
        c.height = _int(_attr(tag, "height")) or c.height
        alt = _attr(tag, "alt") or ""
        if not c.skipped and IMG_SKIP_RE.search(skip_target.lower()):
            c.skipped = "name/alt matches skip pattern"
        known = [d for d in (c.width, c.height) if d]
        if not c.skipped and known and max(known) < MIN_DIM_PX:
            c.skipped = f"too small ({c.width}x{c.height})"
        if c.is_data and not c.skipped and c.data_bytes < 1024:
            c.skipped = "tiny data URI"
        c.alt_src_fee = bool(_ALT_SRC_FEE_RE.search(alt + " " + (c.src if not c.is_data else "")))
        window = masked[max(0, m.start() - WINDOW): m.end() + WINDOW]
        c.money_nearby = bool(_MONEY_NEAR_RE.search(_strip_tags(window)))
        # Nearest preceding heading-ish element decides the block.
        prev = None
        for h in heads:
            if h[0] < m.start():
                prev = h
            else:
                break
        if prev and prev[2] and m.start() - prev[1] <= HEADING_REACH_CHARS:
            c.heading = prev[2]
        out.append(c)
    return out


def select_fee_images(html: str, base_url: str, *, strict: bool = False) -> List[ImageCandidate]:
    """Candidates worth sending to vision, each with `rules` filled in,
    largest first. strict=True keeps only images under a fee heading
    (used on the main event page, where promo banners with money words are
    common)."""
    picked: List[ImageCandidate] = []
    seen = set()
    for c in scan_images(html, base_url):
        if c.skipped or c.src in seen:
            continue
        if c.heading:
            c.rules.append(f"fee_heading_block:{c.heading[:40]}")
        if not strict:
            if c.money_nearby:
                c.rules.append("money_words_nearby")
            if c.alt_src_fee and c.substantial:
                c.rules.append("alt_src_fee_word")
        if not c.rules:
            continue
        seen.add(c.src)
        picked.append(c)
    picked.sort(key=lambda c: -c.area)
    return picked


def fee_image_signal(html: str, base_url: str = "") -> Optional[ImageCandidate]:
    """Audit signal: a fee/registration heading plus a substantial image
    near it. Returns the first such image or None. Detection only."""
    for c in scan_images(html, base_url):
        if c.heading and not c.skipped and c.substantial:
            return c
    return None
