"""Vision-LLM helpers — extract structured data from images.

Used by extractors where the source publishes pricing (or other tabular
data) as PNG/JPEG images instead of HTML. Common for flagship conference
subsites built on tools like idloom.events / Cvent.

We use NVIDIA's hosted Llama 3.2 90B Vision via the same OpenAI-compatible
endpoint the scraper already authenticates against for Kimi K2.6. Same
KIMI_API_KEY, same KIMI_BASE_URL — only the model name changes.

LESSON #4 (cloud LLM rate limits): every call returns None on failure
rather than raising. Caller must handle None — typical fallback is to
leave pricing empty and link out to the source's fees page.

LESSON #6 (model EOLs): vision model name lives in KIMI_VISION_MODEL env
var. To rotate, edit `.env` only — no code change.
"""

from __future__ import annotations
import base64
import json
import logging
import os
import re
from typing import List, Optional

import httpx
from openai import OpenAI

from config import KIMI_API_KEY, KIMI_BASE_URL

logger = logging.getLogger(__name__)

# Rotated 2026-07-31: meta/llama-3.2-90b-vision-instruct returns wordy
# prose on complex fee tables (fails JSON parse), and Llama-3.2-11b-vision
# collapses multi-column pricing to a single price per row.
# nvidia/nemotron-nano-12b-v2-vl correctly extracts row × column into
# separate tiers (verified 2026-07-31 on ESTRO Meets Asia FEE-EmA.jpg).
VISION_MODEL = os.environ.get("KIMI_VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl")

_client: Optional[OpenAI] = None


def _client_get() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
    return _client


def fetch_image_as_data_url(url: str, *, timeout: float = 30.0) -> Optional[str]:
    """Download an image and return it as a base64 data URL (NVIDIA's hosted
    Llama Vision accepts data URLs as inline image input via the OpenAI
    chat-completions image_url format)."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (MedConf vision)"}) as c:
            resp = c.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/png").split(";")[0].strip()
            b64 = base64.b64encode(resp.content).decode()
            return f"data:{content_type};base64,{b64}"
    except Exception as e:
        logger.warning(f"vision: image fetch failed for {url}: {e}")
        return None


def extract_json(
    image_urls: List[str],
    prompt: str,
    *,
    max_tokens: int = 2000,
    timeout: float = 90.0,
) -> Optional[dict]:
    """Send one or more images + a prompt to the vision model. Returns the
    parsed JSON object on success, None on any failure (network error,
    rate limit, JSON parse miss).

    The prompt should instruct the model to return ONLY a JSON object — we
    strip ```json fences and locate the first {...} block before parsing.
    """
    if not image_urls:
        return None

    # Build a multi-content message: prompt + each image
    content: list = [{"type": "text", "text": prompt}]
    for url in image_urls:
        # NVIDIA accepts either http(s) URLs or data URLs. Data URLs are
        # safer for redirect-laden idloom etc.
        if url.startswith("data:"):
            content.append({"type": "image_url", "image_url": {"url": url}})
        else:
            data_url = fetch_image_as_data_url(url)
            if not data_url:
                continue
            content.append({"type": "image_url", "image_url": {"url": data_url}})

    if len(content) == 1:
        # No images successfully attached
        return None

    try:
        resp = _client_get().chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0.0,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"vision: API call failed: {type(e).__name__}: {e}")
        return None

    # Strip code fences + find the first JSON object
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"vision: JSON parse failed: {e}; raw[:300]={raw[:300]!r}")
        return None


# --------------------------------------------------------------------------
# Convenience: pricing-from-images
# --------------------------------------------------------------------------

PRICING_PROMPT = """This image is a registration-fee table for a medical conference. It has two dimensions:
- ROWS group by attendee type (e.g. "Consultant", "Trainee", "Emerging Countries", "EmA Registration") within sections (e.g. "All Day Registration", "One Day Registration", "Full Congress", "Day Rate").
- COLUMNS are timeframes or bands (e.g. "Early Rate", "Late Rate", "Desk Rate", "Standard", "Super Early Bird").

Emit ONE JSON tier per (row × column) cell. Use a composite tier_label that preserves ALL dimensions, joined by " · ", e.g.
    "All Day Registration · Emerging Countries · Early Rate"
    "Consultant · Member · 2-day"

Output ONLY this JSON shape, no prose, no markdown fences:

{
  "tiers": [
    {
      "tier_label": "...",
      "price": 0,
      "currency": "GBP",
      "is_early_bird": false,
      "early_bird_deadline": null
    }
  ]
}

Rules:
- Include EVERY dimension (section, attendee type, timeframe/band) in every tier_label, separated by " · ".
- currency: read €/£/$ symbols. Use "GBP", "USD", "EUR" — default GBP if unclear.
- is_early_bird true ONLY for columns/rows explicitly labelled "Early", "Super Early Bird" etc.
- early_bird_deadline: ISO YYYY-MM-DD ONLY if the year is visible in the image. Do NOT guess a year.
- If a single price spans multiple columns (one flat rate shown across a merged cell), emit ONE tier for that row (not duplicates).
- Be exhaustive but do NOT invent rows that aren't visible.
- If no fee table is visible in the image, return {"tiers": []}.
"""


def extract_pricing_from_images(image_urls: List[str]) -> list[dict]:
    """High-level helper: send pricing images to the vision model and
    return a list of pricing_tier dicts ready for insertion.

    NVIDIA's hosted Llama Vision accepts ONE image per request, so we
    call it once per image and merge the results. Each image typically
    represents one pricing band (super early bird / early bird / standard
    / etc) so a 4-image fees page produces ~30-120 tiers across the bands.

    Returns [] on total failure. Partial failures are tolerated — if 1 of
    4 images fails, we keep the 3 successful ones.
    """
    if not image_urls:
        return []
    all_tier_dicts: list[dict] = []
    for url in image_urls:
        result = extract_json([url], PRICING_PROMPT, max_tokens=3000)
        if not result or "tiers" not in result:
            logger.warning(f"vision: no tiers extracted from {url}")
            continue
        all_tier_dicts.extend(result["tiers"])
    tiers: list[dict] = []
    for t in all_tier_dicts:
        try:
            price = float(t.get("price"))
        except (TypeError, ValueError):
            continue
        label = str(t.get("tier_label", "")).strip()[:200]
        if not label or price <= 0:
            continue
        currency = str(t.get("currency", "GBP")).upper()[:3]
        tiers.append({
            "tier_label": label,
            "price_gbp": price,        # historical column name; currency disambiguates
            "currency": currency,
            "is_early_bird": bool(t.get("is_early_bird")),
            "early_bird_deadline": t.get("early_bird_deadline"),
        })
    # Dedupe by (label, price)
    seen = set()
    out: list[dict] = []
    for t in tiers:
        key = (t["tier_label"], t["price_gbp"])
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out
