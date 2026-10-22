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
            .select("id,society,active").execute().data
        )
    except Exception as e:  # network / auth / import
        print(f"ERROR: could not fetch scraper_sources: {e}", file=sys.stderr)
        return 2

    missing = find_missing(rows, keys)
    for sid, soc in missing:
        print(f"MISSING  id={sid:03d}  society='{soc}'  → add to medconf-website/src/lib/taxonomy/societies.ts")
    for sid, soc in long_codes(rows):
        print(f"WARN     id={sid:03d}  society='{soc}' is {len(soc)} chars (> {MAX_CODE_LEN}); use an acronym or short brand")

    if missing:
        print(f"FAIL — {len(missing)} society code(s) missing from the website taxonomy")
        return 1
    n = len({r["society"] for r in rows if r.get("active") and r.get("society") and r["society"] != "Community"})
    print(f"OK — {n} active society codes all present in the website taxonomy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
