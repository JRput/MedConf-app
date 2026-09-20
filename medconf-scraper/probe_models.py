#!/usr/bin/env python
# probe_models.py
"""Fail-loud liveness probe for the LLM model chains.

Run before the daily scrape (see .github/workflows/scrape-daily.yml's
probe-models job) so a fully-dead chain fails the CI run red BEFORE 29
parallel scrape workers start silently no-op'ing on every LLM call.

Only KIMI_API_KEY (+ optional KIMI_BASE_URL) is required — importing
config.py does not force SUPABASE_URL/SUPABASE_KEY, and this script
never calls config.validate_config().

Real completions only: NVIDIA's /v1/models listing still advertises
models that return 410/404 the moment you actually call them, so a
model only counts as LIVE if a real chat.completions.create() returns
content.

Exit codes:
  0 — first model of every chain is live.
  0 — a chain's primary is dead but a fallback further down is live
      (prints a ::warning:: naming exactly what to fix).
  1 — an entire chain has no live model (prints a ::error::).
"""

from __future__ import annotations
import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional

from openai import OpenAI

from config import KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL_CHAIN, KIMI_VISION_MODEL_CHAIN

MAX_RETRIES = 3
RETRY_BACKOFF_SECS = 2.0

# 1x1 transparent PNG, generated in-memory — no network fetch needed to
# prove a vision model actually accepts an image_url payload.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_TINY_PNG_DATA_URL = f"data:image/png;base64,{_TINY_PNG_B64}"


@dataclass
class ProbeResult:
    chain: str
    model: str
    status: str  # LIVE | DEAD | ERROR
    latency_s: Optional[float]
    detail: str


def _is_transient(exc: Exception) -> bool:
    """429 / timeout / 5xx — worth retrying before calling it ERROR."""
    status = getattr(exc, "status_code", None)
    if status == 429 or (isinstance(status, int) and status >= 500):
        return True
    name = type(exc).__name__
    return name in ("APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError")


def _is_gone(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ == "NotFoundError" or status in (404, 410)


def _probe_text(client: OpenAI, model: str) -> ProbeResult:
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=400,
                temperature=0.0,
                messages=[{"role": "user", "content": 'Reply with strict JSON only: {"word": "hello"}'}],
            )
            dt = time.time() - t0
            content = (resp.choices[0].message.content or "").strip()
            if content:
                return ProbeResult("text", model, "LIVE", dt, content[:80])
            # Empty content on a "stop" finish is unusual but not a dead
            # model — treat as ERROR (transient/config issue), not DEAD.
            return ProbeResult("text", model, "ERROR", dt, f"empty content, finish={resp.choices[0].finish_reason}")
        except Exception as e:
            dt = time.time() - t0
            if _is_gone(e):
                return ProbeResult("text", model, "DEAD", dt, str(e)[:200])
            last_exc = e
            if _is_transient(e) and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECS * attempt)
                continue
            return ProbeResult("text", model, "ERROR", dt, f"{type(e).__name__}: {str(e)[:150]}")
    return ProbeResult("text", model, "ERROR", None, f"{type(last_exc).__name__}: {last_exc}")


def _probe_vision(client: OpenAI, model: str) -> ProbeResult:
    content = [
        {"type": "text", "text": "Reply with strict JSON only: {\"seen\": true}"},
        {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URL}},
    ]
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=400, temperature=0.0, messages=[{"role": "user", "content": content}]
            )
            dt = time.time() - t0
            out = (resp.choices[0].message.content or "").strip()
            if out:
                return ProbeResult("vision", model, "LIVE", dt, out[:80])
            return ProbeResult("vision", model, "ERROR", dt, f"empty content, finish={resp.choices[0].finish_reason}")
        except Exception as e:
            dt = time.time() - t0
            if _is_gone(e):
                return ProbeResult("vision", model, "DEAD", dt, str(e)[:200])
            last_exc = e
            if _is_transient(e) and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECS * attempt)
                continue
            return ProbeResult("vision", model, "ERROR", dt, f"{type(e).__name__}: {str(e)[:150]}")
    return ProbeResult("vision", model, "ERROR", None, f"{type(last_exc).__name__}: {last_exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if not KIMI_API_KEY:
        print("::error::probe_models: KIMI_API_KEY is not set", file=sys.stderr)
        return 1

    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL, timeout=30.0, max_retries=0)

    chains = {"text": KIMI_MODEL_CHAIN, "vision": KIMI_VISION_MODEL_CHAIN}
    results: list[ProbeResult] = []
    for chain_name, models in chains.items():
        probe_fn = _probe_text if chain_name == "text" else _probe_vision
        for model in models:
            results.append(probe_fn(client, model))

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(f"{'CHAIN':<8} {'MODEL':<42} {'STATUS':<7} {'LATENCY':<10} DETAIL")
        for r in results:
            lat = f"{r.latency_s:.1f}s" if r.latency_s is not None else "-"
            print(f"{r.chain:<8} {r.model:<42} {r.status:<7} {lat:<10} {r.detail}")

    exit_code = 0
    for chain_name, models in chains.items():
        chain_results = [r for r in results if r.chain == chain_name]
        live = [r for r in chain_results if r.status == "LIVE"]
        primary = chain_results[0]
        if not live:
            print(f"::error::probe_models: entire '{chain_name}' chain is dead. "
                  f"Tried: {[r.model for r in chain_results]}", file=sys.stderr)
            exit_code = 1
        elif primary.status != "LIVE":
            first_live = live[0]
            print(f"::warning::probe_models: primary '{chain_name}' model '{primary.model}' is "
                  f"{primary.status} — falling back to '{first_live.model}'. Remove '{primary.model}' "
                  f"from the chain and promote '{first_live.model}' once confirmed stable.", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
