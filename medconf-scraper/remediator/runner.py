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
import os
import time
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Iterable, Optional

from .detector import detect_gaps_for_rows, order_gap_rows
from .fetcher import PageCache
from .fixers import REGISTRY as FIXERS
from .validators import validate
from .report import write_report
from .explorer import (
    EXPLORERS, set_source_deadline, get_source_deadline, source_time_up,
    reset_fetch_state, fetch_stats, close_render_browser,
)
from .learned_patterns import record_success, get_promoted_patterns

logger = logging.getLogger(__name__)

# Hard wall-clock budget per source (2026-10-03). Group E of the nightly job
# was cancelled at its 90-min cap because one slow source (FPH 860 s, then
# ESC/ACPGBI) could eat the whole group. After this many seconds the
# remaining rows of the source are skipped with a warning; the report says so.
LLM_CALL_HARD_S = float(os.environ.get("REMEDIATOR_LLM_CALL_HARD_S", "75"))
SOURCE_BUDGET_S = float(os.environ.get("REMEDIATOR_SOURCE_BUDGET_S", "600"))


def _get_supabase():
    from database import supabase
    return supabase


def _llm_call_factory():
    """Mint a tight llm_call closure using the existing scraper LLM client."""
    from openai import OpenAI
    from config import KIMI_API_KEY, KIMI_BASE_URL
    from llm_client import chat_completion
    from vision import call_with_hard_timeout
    # max_retries=0: SDK retries multiplied each hang (see vision._client_get).
    client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL, max_retries=0)

    def call(prompt: str, *, max_tokens: int = 800) -> Optional[str]:
        try:
            # Hard wall-clock cap per call, also clipped to what is left of
            # the source budget (+10 s grace) so one hung call can't overrun it.
            cap = LLM_CALL_HARD_S
            dl = get_source_deadline()
            if dl is not None:
                cap = max(10.0, min(cap, dl - time.time() + 10.0))
            resp = call_with_hard_timeout(
                lambda: chat_completion(
                    client,
                    chain="text",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                    timeout=60.0,
                ),
                cap,
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


def remediate_source(source_id: int, only_ids: Optional[Iterable[int]] = None) -> dict:
    """Run the full remediator pass on one source. Returns the summary dict.
    `only_ids` restricts the pass to those conference ids (targeted re-runs)."""
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
    gaps_per_row = order_gap_rows(gaps_per_row)
    if only_ids is not None:
        _keep = {int(i) for i in only_ids}
        gaps_per_row = [(r, g) for r, g in gaps_per_row if r["id"] in _keep]
    events_with_gaps = len(gaps_per_row)
    logger.info(
        f"remediator source {source_id}: first rows this run: "
        f"{[r['id'] for r, _ in gaps_per_row[:3]]}"
    )
    logger.info(
        f"remediator source {source_id}: "
        f"{events_with_gaps}/{len(conferences)} rows have gaps"
    )

    llm_call = _llm_call_factory()
    reset_fetch_state()
    set_source_deadline(started + SOURCE_BUDGET_S)
    rows_skipped = 0
    attempted = 0
    budget_exhausted = False
    skipped_rows: list = []
    patches_applied: list = []
    patches_rejected: list = []
    patches_couldnt_fix: list = []
    explorer_trails: list = []  # audit trails from Tier 2 escalations

    with PageCache() as cache:
        for row, gaps in gaps_per_row:
            if source_time_up():
                rows_skipped += 1
                skipped_rows.append(row)
                if not budget_exhausted:
                    budget_exhausted = True
                continue
            attempted += 1
            try:
                sb.table("conferences").update(
                    {"remediation_attempted_at": datetime.now(timezone.utc).isoformat()}
                ).eq("id", row["id"]).execute()
            except Exception as e:
                logger.warning(f"remediator: attempt stamp failed for {row['id']}: {e}")
            url = row.get("source_url")
            page_text = cache.get(url) if url else None
            page_html = cache.get_html(url) if url else None
            unfixed = []
            row = {**row, "_detail_is_multipage": bool(source.get("detail_is_multipage"))}
            done_fields: set = set()
            for field in gaps:
                if field in done_fields:
                    continue
                fixer = FIXERS.get(field)
                value: Any = None
                method: Optional[str] = None
                trail_dict: Optional[dict] = None
                result = None

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

                # TIER 1.5 — try previously-promoted patterns before Tier 2.
                # If Tier 2 explorer has previously found <field> via
                # <method>/<subpage> on this domain 3+ times, skip the LLM
                # step and go straight to that sub-page. Saves an LLM
                # call per event on well-known sources.
                if value is None and url:
                    try:
                        promoted = get_promoted_patterns(url, field)
                        for p in promoted:
                            sub = p.get("subpage_path")
                            if not sub:
                                continue
                            sub_url = url.rstrip("/") + sub
                            sub_text = cache.get(sub_url)
                            if not sub_text:
                                continue
                            # Re-run the fixer against the sub-page text
                            if fixer:
                                try:
                                    if field == "specialty":
                                        v, m = fixer(row, sub_text, llm_call, society=society)
                                    else:
                                        v, m = fixer(row, sub_text, llm_call)
                                    if v is not None:
                                        value = v
                                        method = f"promoted:{p['method']}:{sub}"
                                        break
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.debug(f"promoted-pattern replay failed: {e}")

                result = None
                # TIER 2 — explorer escalation when Tier 1 returns null
                if value is None and field in EXPLORERS and url and not source_time_up():
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
                        # Side finding from a nav page (abstract deadline on
                        # an "Abstracts" page found while hunting for fees).
                        _ab = (getattr(result, "extras", None) or {}).get("abstract_status")
                        if _ab and field == "pricing" and "abstract_status" in gaps \
                                and validate("abstract_status", _ab):
                            if _patch_row(sb, row["id"], "abstract_status", _ab):
                                done_fields.add("abstract_status")
                                patches_applied.append({
                                    "conference_id": row["id"],
                                    "conference_name": (row.get("conference_name") or "")[:60],
                                    "field": "abstract_status",
                                    "value_before": "(complex)",
                                    "value_after": str(_ab)[:200],
                                    "method": "explorer:nav_abstract",
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
                    # No fees, but the explorer reached an external event page:
                    # keep it as organiser_url so the next run can retry cheaply.
                    _ext = getattr(result, "external_url", None) if (result is not None and field == "pricing") else None
                    if _ext and row.get("organiser_url") in (None, "", row.get("source_url")):
                        if _patch_row(sb, row["id"], "organiser_url", _ext):
                            patches_applied.append({
                                "conference_id": row["id"],
                                "conference_name": (row.get("conference_name") or "")[:60],
                                "field": "organiser_url",
                                "value_before": str(row.get("organiser_url"))[:80],
                                "value_after": _ext[:200],
                                "method": "external_link_recorded:no_fees_found",
                            })
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
                    # Tier 3 found fees on an external page: point the
                    # organiser link (and the booking link, if it was just
                    # the listing page) at it.
                    ext = getattr(result, "external_url", None) if field == "pricing" else None
                    if ext:
                        link_patches = {}
                        if row.get("organiser_url") in (None, "", row.get("source_url")):
                            link_patches["organiser_url"] = ext
                        if row.get("booking_url") in (None, "", row.get("source_url")):
                            link_patches["booking_url"] = ext
                        for lf, lv in link_patches.items():
                            if _patch_row(sb, row["id"], lf, lv):
                                patches_applied.append({
                                    "conference_id": row["id"],
                                    "conference_name": (row.get("conference_name") or "")[:60],
                                    "field": lf,
                                    "value_before": str(row.get(lf))[:80],
                                    "value_after": lv[:200],
                                    "method": f"external_link_follow:{method}",
                                })
                else:
                    unfixed.append(field)
            if unfixed:
                patches_couldnt_fix.append({
                    "conference_id": row["id"],
                    "conference_name": (row.get("conference_name") or "")[:60],
                    "fields": unfixed,
                })

    set_source_deadline(None)
    close_render_browser()
    duration = time.time() - started
    oldest_unattempted_days = None
    if skipped_rows:
        now_dt = datetime.now(timezone.utc)
        ages = []
        for r in skipped_rows:
            v = r.get("remediation_attempted_at")
            if not v:
                ages.append(None)
                continue
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            ages.append((now_dt - d).total_seconds() / 86400)
        known = [a for a in ages if a is not None]
        oldest_unattempted_days = (
            "never" if any(a is None for a in ages) else round(max(known), 1)
        )
        stale7 = sum(1 for a in ages if a is None or a > 7)
        logger.warning(
            f"remediator source {source_id}: time budget {SOURCE_BUDGET_S:.0f}s "
            f"exhausted — attempted {attempted}, skipped {rows_skipped}; "
            f"{stale7} rows unattempted for >7 days (oldest: {oldest_unattempted_days})"
        )
    stats = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in fetch_stats.items()}
    logger.info(f"remediator source {source_id}: done in {duration:.0f}s, fetch stats {stats}")
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
        budget_exhausted=budget_exhausted,
        rows_skipped=rows_skipped,
        budget_s=SOURCE_BUDGET_S,
        fetch_stats=stats,
    )

    return {
        "source_id": source_id,
        "events_scraped": len(conferences),
        "events_with_gaps": events_with_gaps,
        "patches_applied": len(patches_applied),
        "patches_rejected": len(patches_rejected),
        "patches_couldnt_fix": len(patches_couldnt_fix),
        "duration_sec": round(duration, 1),
        "budget_exhausted": budget_exhausted,
        "rows_skipped_by_budget": rows_skipped,
        "attempted": attempted,
        "skipped_budget": rows_skipped,
        "oldest_unattempted_days": oldest_unattempted_days,
        "report_path": str(report_path),
    }
