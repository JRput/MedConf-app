"""
enrich_submissions.py

Pre-moderation enrichment of community submissions (Community Contributions v2,
MISSION_BOARD_CONTRIBUTIONS.md section 1.4). Runs every 6 hours via GitHub
Actions (enrich-submissions.yml).

For each community_contributions row with status='pending' and
enrichment_status='waiting' (older than 2 minutes), the job:
  1. builds a row-shaped dict from the payload (add_info: from the listed
     conference row, overlaid with the user's values),
  2. SSRF-checks the organiser URL (http/https only, no IP literals, no
     loopback / private / link-local / reserved resolution),
  3. fetches the page with the remediator's PageCache (same anti-bot detector),
  4. runs EVERY fixer in remediator.fixers.REGISTRY, including for fields the
     user already filled (cross-check),
  5. writes enrichment = {field: {value, method, agrees}}, enrichment_status,
     enriched_at.

Usage:
  python enrich_submissions.py                 # normal run (writes)
  python enrich_submissions.py --dry-run       # no writes, prints what would happen
  python enrich_submissions.py --id <uuid>     # one submission (any state)

Exit code: 0 even when some submissions fail; 1 only on config errors.
"""

import argparse
import ipaddress
import json
import logging
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

BATCH_LIMIT = 25
MIN_AGE_MINUTES = 2
RUN_BUDGET_S = 10 * 60
MAX_FETCHES_PER_SUBMISSION = 3

logger = logging.getLogger("enrich_submissions")

# Payload fields that map one-to-one onto a conferences column / fixer name.
_SIMPLE_FIELDS = ("description", "venue_name", "city", "event_format",
                  "cpd_points", "specialty")


# ---------------------------------------------------------------- SSRF guard

def _ip_is_blocked(ip: "ipaddress._BaseAddress") -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # not is_global covers loopback, RFC1918, link-local, 0.0.0.0/8, CGNAT,
    # fc00::/7, fe80::/10, ::1, reserved ranges.
    return (not ip.is_global) or ip.is_multicast or ip.is_unspecified


def check_url_safe(url: Optional[str]) -> tuple:
    """Return (ok, reason). Never fetches anything itself."""
    if not url or not isinstance(url, str):
        return False, "no url"
    try:
        p = urlparse(url.strip())
    except Exception:
        return False, "unparseable url"
    if p.scheme not in ("http", "https"):
        return False, "scheme not http/https"
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False, "no hostname"
    if host == "localhost" or host.endswith(".localhost"):
        return False, "localhost"
    try:
        ipaddress.ip_address(host)
        return False, "ip literal"
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except Exception:
        return False, "unresolvable host"
    if not infos:
        return False, "unresolvable host"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False, "bad address"
        if _ip_is_blocked(ip):
            return False, "non-public address"
    return True, ""


# ------------------------------------------------------------ row building

def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def build_row(sub: dict, conference: Optional[dict]) -> tuple:
    """Return (row, user_values, url). user_values = what the submitter typed."""
    payload = sub.get("payload") or {}
    kind = sub.get("kind")
    if kind == "add_info":
        user = dict(payload.get("fields") or {})
        row = dict(conference or {})
        url = ((conference or {}).get("organiser_url")
               or (conference or {}).get("booking_url")
               or (conference or {}).get("source_url"))
    else:
        user = {k: v for k, v in payload.items()}
        row = {k: v for k, v in payload.items()}
        url = payload.get("organiser_url")
    for k, v in user.items():
        if not _blank(v):
            row[k] = v
    if "fees" in payload:
        user["fees"] = payload.get("fees")
    row["source_url"] = url
    row["_detail_is_multipage"] = False
    return row, user, url


# ---------------------------------------------------------------- compare

def _norm(v: Any) -> str:
    return " ".join(str(v).split()).casefold()


def _num(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _price_set(tiers: Any, price_key: str) -> set:
    out = set()
    for t in tiers or []:
        if isinstance(t, dict):
            p = _num(t.get(price_key))
            if p is not None:
                out.add(p)
    return out


def compute_agrees(field: str, found: Any, user: dict) -> Optional[bool]:
    """True/False when the submitter supplied this field, None when they did not."""
    if field == "pricing":
        fees = user.get("fees") or {}
        mine = _price_set(fees.get("tiers") if isinstance(fees, dict) else None, "price")
        if not mine:
            return None
        theirs = _price_set(found, "price_gbp")
        return bool(theirs) and mine.issubset(theirs)
    if field == "abstract_status":
        found = found if isinstance(found, dict) else {}
        checks = []
        if not _blank(user.get("abstract_deadline")):
            checks.append(_norm(user["abstract_deadline"])[:10]
                          == _norm(found.get("abstract_deadline") or "")[:10])
        if user.get("abstract_open") is True:
            checks.append(found.get("abstract_open") is True)
        return all(checks) if checks else None
    mine = user.get(field)
    if _blank(mine):
        return None
    if field == "cpd_points":
        a, b = _num(mine), _num(found)
        return a is not None and a == b
    return _norm(mine) == _norm(found)


def _json_safe(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


# -------------------------------------------------------------- enrichment

class _FetchBudget:
    def __init__(self, cache, limit: int):
        self.cache, self.limit, self.used = cache, limit, 0

    def can(self) -> bool:
        return self.used < self.limit

    def text(self, url: str) -> Optional[str]:
        if not self.can():
            return None
        self.used += 1
        return self.cache.get(url)


def enrich_one(sub: dict, conference: Optional[dict], cache, llm_call: Callable,
               fixers: dict, challenge_check: Callable,
               url_check: Callable = check_url_safe) -> tuple:
    """Return (enrichment_status, enrichment_dict). Never raises."""
    row, user, url = build_row(sub, conference)
    ok, reason = url_check(url)
    if not ok:
        return "skipped", {"_error": "url rejected"}
    try:
        budget = _FetchBudget(cache, MAX_FETCHES_PER_SUBMISSION)
        text = budget.text(url)
        html = cache.get_html(url)
        if not text or not text.strip() or challenge_check(html):
            return "blocked", {"_error": "page blocked or empty"}
        enrichment: dict = {}
        for field, fixer in fixers.items():
            value, method = _run_fixer(field, fixer, row, text, llm_call)
            if value is None:
                value, method = _try_promoted(field, fixer, row, url, budget,
                                              llm_call, url_check)
            if value is None:
                continue
            safe = _json_safe(value)
            enrichment[field] = {"value": safe, "method": method,
                                 "agrees": compute_agrees(field, safe, user)}
        return "fetched", enrichment
    except Exception as e:  # noqa: BLE001 - one bad submission must not stop the run
        return "failed", {"_error": f"{type(e).__name__}: {e}"[:300]}


def _run_fixer(field, fixer, row, text, llm_call):
    try:
        if field == "specialty":
            return fixer(row, text, llm_call, society=None)
        return fixer(row, text, llm_call)
    except Exception as e:  # noqa: BLE001
        logger.warning("fixer %s crashed: %s", field, e)
        return None, None


def _try_promoted(field, fixer, row, url, budget, llm_call, url_check):
    """Optional: replay learned sub-page patterns, within the fetch cap."""
    try:
        from remediator.learned_patterns import get_promoted_patterns
        for p in get_promoted_patterns(url, field):
            if not budget.can():
                break
            sub = p.get("subpage_path")
            if not sub:
                continue
            sub_url = url.rstrip("/") + sub
            if not url_check(sub_url)[0]:
                continue
            sub_text = budget.text(sub_url)
            if not sub_text:
                continue
            v, _m = _run_fixer(field, fixer, row, sub_text, llm_call)
            if v is not None:
                return v, f"promoted:{p.get('method')}:{sub}"
    except Exception as e:  # noqa: BLE001
        logger.debug("promoted-pattern replay failed: %s", e)
    return None, None


# --------------------------------------------------------------------- IO

def fetch_pending(sb, sub_id: Optional[str]) -> list:
    q = sb.table("community_contributions").select("*")
    if sub_id:
        q = q.eq("id", sub_id)
    else:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(minutes=MIN_AGE_MINUTES)).isoformat()
        q = (q.eq("status", "pending").eq("enrichment_status", "waiting")
             .lt("created_at", cutoff).order("created_at", desc=False)
             .limit(BATCH_LIMIT))
    return q.execute().data or []


def fetch_conference(sb, conference_id) -> Optional[dict]:
    if conference_id is None:
        return None
    rows = (sb.table("conferences").select("*").eq("id", conference_id)
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def _default_llm_call():
    try:
        from remediator.runner import _llm_call_factory
        return _llm_call_factory()
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: LLM unavailable ({e}); heuristic fixers only")
        return lambda prompt, **kw: None


def run(args, sb=None, cache_factory=None, llm_call=None, fixers=None,
        challenge_check=None, url_check=check_url_safe) -> int:
    from dotenv import load_dotenv
    load_dotenv()
    if sb is None:
        missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY") if not os.environ.get(k)]
        if missing:
            print(f"ERROR: missing required environment variables: {', '.join(missing)}")
            return 1
        from supabase import create_client
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        if not os.environ.get("KIMI_API_KEY"):
            print("WARNING: KIMI_API_KEY not set; heuristic fixers only")
    if fixers is None:
        from remediator.fixers import REGISTRY
        fixers = REGISTRY
    if challenge_check is None:
        from browser import looks_like_challenge as challenge_check
    if cache_factory is None:
        from remediator.fetcher import PageCache as cache_factory
    if llm_call is None:
        llm_call = _default_llm_call()

    subs = fetch_pending(sb, args.id)
    print(f"enrich_submissions: {len(subs)} submission(s) to enrich"
          f"{' (dry run)' if args.dry_run else ''}")
    started = time.time()
    totals: dict = {}
    with cache_factory() as cache:
        for sub in subs:
            if time.time() - started > RUN_BUDGET_S:
                print("budget exceeded; stopping cleanly")
                break
            try:
                conf = (fetch_conference(sb, sub.get("conference_id"))
                        if sub.get("kind") == "add_info" else None)
                status, enrichment = enrich_one(sub, conf, cache, llm_call, fixers,
                                                challenge_check, url_check)
            except Exception as e:  # noqa: BLE001
                status, enrichment = "failed", {"_error": f"{type(e).__name__}: {e}"[:300]}
            totals[status] = totals.get(status, 0) + 1
            fields = [k for k in enrichment if not k.startswith("_")]
            print(f"{sub.get('id')} kind={sub.get('kind')} -> {status}"
                  f" fields={','.join(fields) or '-'}"
                  f"{' error=' + enrichment['_error'] if '_error' in enrichment else ''}")
            if not args.dry_run:
                try:
                    sb.table("community_contributions").update({
                        "enrichment": enrichment,
                        "enrichment_status": status,
                        "enriched_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", sub["id"]).execute()
                except Exception as e:  # noqa: BLE001
                    print(f"  write failed for {sub.get('id')}: {e}")
    print("totals: " + (", ".join(f"{k}={v}" for k, v in sorted(totals.items())) or "none"))
    return 0


def main(argv=None, **kw) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="no writes")
    ap.add_argument("--id", help="enrich a single submission uuid")
    return run(ap.parse_args(argv), **kw)


if __name__ == "__main__":
    sys.exit(main())
