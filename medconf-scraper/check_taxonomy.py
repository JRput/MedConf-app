#!/usr/bin/env python
# check_taxonomy.py
"""Guard: every active scraper_sources.society code must exist in the website taxonomy.

The website's medconf-website/src/lib/taxonomy/societies.ts must list every
society code used by an active source, otherwise the society is invisible on
/societies and falls under "Other" in the filter picker. Forgotten on waves
2a-2d, hence this check (daily CI job `taxonomy-check`, and run it locally
before pushing a registration).

Needs SUPABASE_URL / SUPABASE_KEY (env or .env in this folder).

Exit codes: 0 ok, 1 missing codes, 2 config/network error.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

MAX_CODE_LEN = 25
DEFAULT_TS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "medconf-website", "src", "lib", "taxonomy", "societies.ts",
)

_KEY_RE = re.compile(
    r"""^\s*(?:
        (?P<bare>[A-Za-z_$][\w$]*)
      | '(?P<sq>(?:[^'\\]|\\.)*)'
      | "(?P<dq>(?:[^"\\]|\\.)*)"
    )\s*:\s*\{""",
    re.VERBOSE,
)


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def parse_taxonomy_keys(ts_source: str) -> set[str]:
    """Top-level keys of the SOCIETIES object literal."""
    keys: set[str] = set()
    inside = False
    for line in ts_source.splitlines():
        if not inside:
            if re.match(r"\s*export\s+const\s+SOCIETIES\b", line):
                inside = True
            continue
        if line.startswith("}"):
            break
        if line.lstrip().startswith("//"):
            continue
        m = _KEY_RE.match(line)
        if not m or "short:" not in line:
            continue
        if m.group("bare") is not None:
            keys.add(m.group("bare"))
        elif m.group("sq") is not None:
            keys.add(_unescape(m.group("sq")))
        else:
            keys.add(_unescape(m.group("dq")))
    return keys


def find_missing(rows: list[dict], keys: set[str]) -> list[tuple[int, str]]:
    out = [
        (r["id"], r["society"])
        for r in rows
        if r.get("active") and r.get("society")
        and r["society"] != "Community" and r["society"] not in keys
    ]
    return sorted(out)


def long_codes(rows: list[dict]) -> list[tuple[int, str]]:
    out = [
        (r["id"], r["society"])
        for r in rows
        if r.get("active") and r.get("society") and len(r["society"]) > MAX_CODE_LEN
    ]
    return sorted(out)


# Coverage-run guard (2026-10-27): a source registered in the last 7 days must
# have a build JSON (Conference_masterlist/wave*/) carrying `coverage_run`, which
# harness.py writes when coverage checks run (default). Sources registered before
# the cutoff are grandfathered; sources with no discoverable build JSON are skipped.
COVERAGE_REQUIRED_FROM = "2026-10-28"
BUILD_GLOB_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Conference_masterlist")


def missing_coverage_runs(rows: list[dict], build_docs: list[dict], now=None,
                          required_from: str = COVERAGE_REQUIRED_FROM) -> list[tuple[int, str]]:
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    cutoff = max(now - timedelta(days=7),
                 datetime.fromisoformat(required_from).replace(tzinfo=timezone.utc))
    by_id: dict = {}
    by_url: dict = {}
    for d in build_docs:
        if d.get("source_id"):
            by_id.setdefault(d["source_id"], []).append(d)
        u = (d.get("source_row") or {}).get("base_url")
        if u:
            by_url.setdefault(u, []).append(d)
    out = []
    for r in rows:
        if not r.get("active") or not r.get("created_at"):
            continue
        c = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
        if c.tzinfo is None:
            c = c.replace(tzinfo=timezone.utc)
        if c < cutoff:
            continue
        docs = by_id.get(r["id"]) or by_url.get(r.get("base_url")) or []
        if docs and not any(d.get("coverage_run") for d in docs):
            out.append((r["id"], r.get("source_name") or ""))
    return sorted(out)


def load_build_docs(root: str = BUILD_GLOB_ROOT) -> list[dict]:
    import glob
    import json
    docs = []
    for f in glob.glob(os.path.join(root, "wave*", "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and "source_row" in d:
            docs.append(d)
    return docs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--taxonomy", default=DEFAULT_TS, help="path to societies.ts")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except ImportError:
        pass

    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY not set", file=sys.stderr)
        return 2
    try:
        with open(args.taxonomy, encoding="utf-8") as f:
            keys = parse_taxonomy_keys(f.read())
    except OSError as e:
        print(f"ERROR: cannot read taxonomy file: {e}", file=sys.stderr)
        return 2
    if not keys:
        print(f"ERROR: no SOCIETIES keys parsed from {args.taxonomy}", file=sys.stderr)
        return 2
    try:
        from supabase import create_client
        rows = (
            create_client(url, key).table("scraper_sources")
            .select("id,society,active,source_name,base_url,created_at").execute().data
        )
    except Exception as e:  # network / auth / import
        print(f"ERROR: could not fetch scraper_sources: {e}", file=sys.stderr)
        return 2

    missing = find_missing(rows, keys)
    for sid, soc in missing:
        print(f"MISSING  id={sid:03d}  society='{soc}'  → add to medconf-website/src/lib/taxonomy/societies.ts")
    for sid, soc in long_codes(rows):
        print(f"WARN     id={sid:03d}  society='{soc}' is {len(soc)} chars (> {MAX_CODE_LEN}); use an acronym or short brand")

    no_cov = missing_coverage_runs(rows, load_build_docs())
    for sid, nm in no_cov:
        print(f"NO_COVERAGE_RUN  id={sid:03d}  {nm}: build JSON lacks `coverage_run` — rerun harness.py (coverage is default)")

    if no_cov:
        print(f"FAIL — {len(no_cov)} recently registered source(s) without a recorded coverage run")
    if missing:
        print(f"FAIL — {len(missing)} society code(s) missing from the website taxonomy")
    if missing or no_cov:
        return 1
    n = len({r["society"] for r in rows if r.get("active") and r.get("society") and r["society"] != "Community"})
    print(f"OK — {n} active society codes all present in the website taxonomy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
