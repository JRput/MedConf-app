#!/usr/bin/env python3
"""P0 triage: masterlist CSV -> triage.json work-list for recon/onboarding.

Dedupes 396 rows into per-domain source candidates, tags domains already
covered by the 23 active scraper sources, ranks by row count (value proxy).
Deterministic — no network, no LLM.
"""
import csv
import json
import re
import urllib.parse
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
CSV = HERE / "Medical_Courses_Conferences_Master_Comprehensive_v1(Master list).csv"
OUT = HERE / "triage.json"

# Domains of the 23 active scraper_sources (production, 2026-08).
ACTIVE_DOMAINS = {
    "rcgp.org.uk": [1],
    "rcseng.ac.uk": [2, 5],
    "rsm.ac.uk": [3],
    "rcp.ac.uk": [4],
    "rcem.ac.uk": [6, 7],
    "rcem-events.uk": [8],
    "rcog.org.uk": [9, 10],
    "rcr.ac.uk": [11, 12],
    "bopa.org.uk": [13],
    "btog.org": [14],
    "asco.org": [15, 16],
    "esmo.org": [17],
    "aacr.org": [18],
    "estro.org": [19],
    "sabcs.org": [20],
    "esgo.org": [21, 22],
    "sitcancer.org": [23],
    "sitc.org": [23],
}

# Known out-of-scope domains (recon will confirm, but pre-tag).
LIKELY_OUT_OF_SCOPE = {
    "e-lfh.org.uk": "e-learning module platform, not dated events",
    "onexamination.com": "exam revision product, not events",
}

EVENT_PATH_HINT = re.compile(
    r"event|conference|course|congress|meeting|cpd|education|training|study-day|exam",
    re.I,
)


def domain_of(url: str) -> str:
    netloc = urllib.parse.urlparse(url.strip()).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def covered_by(domain: str):
    for active, ids in ACTIVE_DOMAINS.items():
        if domain == active or domain.endswith("." + active):
            return ids
    return None


def main():
    rows = list(csv.DictReader(open(CSV, encoding="latin-1")))
    groups = defaultdict(list)
    for i, r in enumerate(rows, start=2):  # CSV line numbers incl. header
        url = (r.get("Website") or "").strip()
        if not url.startswith("http"):
            continue
        groups[domain_of(url)].append(
            {
                "csv_line": i,
                "name": r["Name"].strip(),
                "category": r["Category"].strip(),
                "type": r["Type"].strip(),
                "specialty": r["Specialty"].strip(),
                "provider": r["Provider"].strip(),
                "region": r["Country/Region"].strip(),
                "url": url,
                "notes": (r.get("Notes") or "").strip(),
            }
        )

    covered, new, out_of_scope = [], [], []
    for domain, items in groups.items():
        urls = sorted({it["url"] for it in items})
        entry = {
            "domain": domain,
            "row_count": len(items),
            "providers": sorted({it["provider"] for it in items}),
            "specialties": sorted({it["specialty"] for it in items}),
            "urls": urls,
            "deep_urls": [u for u in urls if urllib.parse.urlparse(u).path.strip("/")],
            "event_hint_urls": [u for u in urls if EVENT_PATH_HINT.search(u)],
            "expected_items": [
                {"name": it["name"], "category": it["category"], "type": it["type"]}
                for it in items
            ],
        }
        ids = covered_by(domain)
        if ids:
            entry["active_source_ids"] = ids
            covered.append(entry)
        elif domain in LIKELY_OUT_OF_SCOPE:
            entry["reason"] = LIKELY_OUT_OF_SCOPE[domain]
            out_of_scope.append(entry)
        else:
            new.append(entry)

    new.sort(key=lambda e: -e["row_count"])
    covered.sort(key=lambda e: -e["row_count"])

    result = {
        "generated_from": CSV.name,
        "total_rows": len(rows),
        "domains_total": len(groups),
        "domains_covered": len(covered),
        "domains_new": len(new),
        "domains_likely_out_of_scope": len(out_of_scope),
        "new": new,
        "covered": covered,
        "likely_out_of_scope": out_of_scope,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f"wrote {OUT}")
    print(
        f"rows={len(rows)} domains={len(groups)} covered={len(covered)} "
        f"new={len(new)} out_of_scope={len(out_of_scope)}"
    )
    print("\ntop 20 new domains by row count:")
    for e in new[:20]:
        print(f"  {e['row_count']:3d}  {e['domain']}  ({e['providers'][0][:45]})")


if __name__ == "__main__":
    main()
