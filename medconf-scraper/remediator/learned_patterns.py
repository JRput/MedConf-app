"""Learned patterns store.

When Tier 2 explorer finds a value via a non-trivial path (sub-page,
vision LLM, full-context LLM), we record where it found it. After PROMOTE_THRESHOLD
successful uses of the same (domain, field, method) combination, the
remediator promotes that path to Tier 1 — next time it tries that path FIRST,
skipping the LLM call.

Patterns persist as JSON at:
  reports/remediation/learned_patterns.json
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROMOTE_THRESHOLD = 3

_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "reports" / "remediation" / "learned_patterns.json"
)


def _load() -> dict:
    if not _PATTERNS_PATH.exists():
        return {"patterns": {}, "version": 1}
    try:
        with open(_PATTERNS_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"learned_patterns: load failed: {e}")
        return {"patterns": {}, "version": 1}


def _save(data: dict) -> None:
    _PATTERNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_PATTERNS_PATH) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, _PATTERNS_PATH)


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def record_success(*, source_url: str, field: str, method: str,
                   subpage_path: Optional[str] = None) -> dict:
    """Record one successful exploration. Returns the updated pattern entry."""
    domain = _domain_of(source_url)
    if not domain:
        return {}
    data = _load()
    patterns = data.setdefault("patterns", {})
    key = f"{domain}|{field}|{method}"
    if subpage_path:
        key += f"|{subpage_path}"
    entry = patterns.get(key, {
        "domain": domain, "field": field, "method": method,
        "subpage_path": subpage_path, "hits": 0, "promoted": False,
    })
    entry["hits"] = entry.get("hits", 0) + 1
    if entry["hits"] >= PROMOTE_THRESHOLD and not entry.get("promoted"):
        entry["promoted"] = True
        logger.info(
            f"learned_patterns: PROMOTED {key} after {entry['hits']} hits"
        )
    patterns[key] = entry
    _save(data)
    return entry


def get_promoted_patterns(source_url: str, field: str) -> list:
    """Return promoted patterns for this (domain, field) — caller tries them
    BEFORE escalating to explorer or LLM."""
    domain = _domain_of(source_url)
    if not domain:
        return []
    data = _load()
    out = []
    for entry in (data.get("patterns") or {}).values():
        if (entry.get("domain") == domain
                and entry.get("field") == field
                and entry.get("promoted")):
            out.append(entry)
    out.sort(key=lambda e: -e.get("hits", 0))
    return out


def all_patterns_summary() -> dict:
    data = _load()
    patterns = list((data.get("patterns") or {}).values())
    return {
        "total": len(patterns),
        "promoted": sum(1 for p in patterns if p.get("promoted")),
        "by_domain": _group_count(patterns, "domain"),
        "by_field": _group_count(patterns, "field"),
    }


def _group_count(items: list, key: str) -> dict:
    out: dict = {}
    for item in items:
        k = item.get(key, "?")
        out[k] = out.get(k, 0) + 1
    return out
