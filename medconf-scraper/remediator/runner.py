"""Remediator orchestrator.

For one source:
  1. Load source row + all scraped conferences + their pricing
  2. Detect gaps per row
  3. For each (row, gap), run the fixer with the source page text
  4. Validate the proposed value
  5. Patch DB if valid; otherwise record as couldn't-fix
  6. Write report
"""

from __future__ import annotations
import logging
import time
from collections import defaultdict
from typing import Any, Optional

from .detector import detect_gaps_for_rows
from .fetcher import PageCache
from .fixers import REGISTRY as FIXERS
from .validators import validate
from .report import write_report
from .explorer import EXPLORERS
from .learned_patterns import record_success

logger = logging.getLogger(__name__)


def _get_supabase():
    from database import supabase
    return supabase


def _llm_call_factory():
    """Mint a tight llm_call closure using the existing scraper LLM client."""
    from openai import OpenAI
    from config import KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL
    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)

    def call(prompt: str, *, max_tokens: int = 800) -> Optional[str]:
        try:
            resp = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=60.0,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"remediator LLM call failed: {e}")
            return None

    return call


def _patch_row(supabase, conference_id: int, field: str, value: Any) -> bool:
    """Apply one patch to the conferences row. Returns True on success."""
    try:
        if field == "pricing":
            # Replace pricing tiers wholesale
            supabase.table("pricing_tiers").delete().eq(
                "conference_id", conference_id
            ).execute()
            rows = []
            for t in value:
                rows.append({
                    "conference_id": conference_id,
                    "tier_label": t["tier_label"],
                    "price_gbp": t["price_gbp"],
                    "currency": t.get("currency", "GBP"),
                    "is_early_bird": t.get("is_early_bird", False),
                    "early_bird_deadline": t.get("early_bird_deadline"),
                })
            if rows:
                supabase.table("pricing_tiers").insert(rows).execute()
            return True
        if field == "abstract_status":
            # value is a dict of field updates
            supabase.table("conferences").update(value).eq("id", conference_id).execute()
            return True
        # Default: single column update
        supabase.table("conferences").update({field: value}).eq("id", conference_id).execute()
        return True
    except Exception as e:
        logger.warning(f"remediator: patch failed for {conference_id}.{field}: {e}")
        return False


def remediate_source(source_id: int) -> dict:
    """Run the full remediator pass on one source. Returns the summary dict."""
    started = time.time()
    sb = _get_supabase()

    source_rows = (
        sb.table("scraper_sources").select("*").eq("id", source_id).execute().data
        or []
    )
    if not source_rows:
        raise RuntimeError(f"source {source_id} not found")
    source = source_rows[0]
    society = source.get("society")

    # Pull live conferences for this source
    conferences = []
    start = 0
    while True:
        chunk = (
            sb.table("conferences")
            .select("*")
            .eq("source_id", source_id)
            .eq("archived", False)
            .range(start, start + 999)
            .execute()
            .data
            or []
        )
        conferences.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000

    if not conferences:
        return {
            "source_id": source_id,
            "events_scraped": 0,
            "patches_applied": [],
            "patches_couldnt_fix": [],
        }

    # Pricing tier presence per conference
    conf_ids = [c["id"] for c in conferences]
    tiers = (
        sb.table("pricing_tiers").select("conference_id").in_("conference_id", conf_ids)
        .execute().data
        or []
    )
    pricing_by_conf: dict = defaultdict(list)
    for t in tiers:
        pricing_by_conf[t["conference_id"]].append(t)

    # Detect gaps
    gaps_per_row = detect_gaps_for_rows(conferences, pricing_by_conf)
    events_with_gaps = len(gaps_per_row)
    logger.info(
        f"remediator source {source_id}: "
        f"{events_with_gaps}/{len(conferences)} rows have gaps"
    )

    llm_call = _llm_call_factory()
    patches_applied: list = []
    patches_rejected: list = []
    patches_couldnt_fix: list = []
    explorer_trails: list = []  # audit trails from Tier 2 escalations

    with PageCache() as cache:
        for row, gaps in gaps_per_row:
            url = row.get("source_url")
            page_text = cache.get(url) if url else None
            page_html = cache.get_html(url) if url else None
            unfixed = []
            for field in gaps:
                fixer = FIXERS.get(field)
                value: Any = None
                method: Optional[str] = None
                trail_dict: Optional[dict] = None

                # TIER 1 — quick fixer
                if fixer:
                    try:
                        if field == "specialty":
                            value, method = fixer(row, page_text or "",
                                                  llm_call, society=society)
                        else:
                            value, method = fixer(row, page_text or "", llm_call)
                    except Exception as e:
                        logger.warning(
                            f"remediator: fixer {field} crashed on {row['id']}: {e}"
                        )

                # TIER 2 — explorer escalation when Tier 1 returns null
                if value is None and field in EXPLORERS and url:
                    try:
                        explorer = EXPLORERS[field]
                        result = explorer(
                            row=row,
                            page_text=page_text or "",
                            page_html=page_html,
                            base_url=url,
                            llm_call=llm_call,
                        )
                        trail_dict = result.to_dict()
                        explorer_trails.append({
                            "conference_id": row["id"],
                            "conference_name": (row.get("conference_name") or "")[:60],
                            **trail_dict,
                        })
                        if result.found and result.value is not None:
                            value = result.value
                            method = f"explorer:{result.method}"
                            # Record for learning loop
                            try:
                                subpath = None
                                if result.method.startswith("subpage"):
                                    if result.audit_trail.subpages_fetched:
                                        subpath = result.audit_trail.subpages_fetched[-1]
                                record_success(
                                    source_url=url, field=field,
                                    method=result.method,
                                    subpage_path=subpath,
                                )
                            except Exception as e:
                                logger.warning(f"learned_patterns record failed: {e}")
                    except Exception as e:
                        logger.warning(
                            f"remediator: explorer {field} crashed on {row['id']}: {e}"
                        )

                if value is None:
                    unfixed.append(field)
                    continue
                if not validate(field, value):
                    patches_rejected.append({
                        "conference_id": row["id"],
                        "field": field,
                        "rejected_value": str(value)[:200],
                        "method": method,
                    })
                    unfixed.append(field)
                    continue
                if _patch_row(sb, row["id"], field, value):
                    patches_applied.append({
                        "conference_id": row["id"],
                        "conference_name": (row.get("conference_name") or "")[:60],
                        "field": field,
                        "value_before": str(row.get(field))[:80] if field not in ("pricing", "abstract_status") else "(complex)",
                        "value_after": str(value)[:200],
                        "method": method,
                    })
                else:
                    unfixed.append(field)
            if unfixed:
                patches_couldnt_fix.append({
                    "conference_id": row["id"],
                    "conference_name": (row.get("conference_name") or "")[:60],
                    "fields": unfixed,
                })

    duration = time.time() - started
    report_path = write_report(
        source_id=source_id,
        source_name=source.get("source_name") or "?",
        society=society,
        events_scraped=len(conferences),
        events_with_gaps=events_with_gaps,
        patches_applied=patches_applied,
        patches_rejected=patches_rejected,
        patches_couldnt_fix=patches_couldnt_fix,
        duration_sec=duration,
        explorer_trails=explorer_trails,
    )

    return {
        "source_id": source_id,
        "events_scraped": len(conferences),
        "events_with_gaps": events_with_gaps,
        "patches_applied": len(patches_applied),
        "patches_rejected": len(patches_rejected),
        "patches_couldnt_fix": len(patches_couldnt_fix),
        "duration_sec": round(duration, 1),
        "report_path": str(report_path),
    }
