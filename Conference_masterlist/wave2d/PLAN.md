# Wave 2d — static HTML + unknown-platform sources (opened 2026-10-21)

Source of truth for ids/slugs/recon: `plan.json`. Probe input: `candidates.json`
(`probe-cloud-access.yml`). Brief: `BRIEF.md` (delta over `../wave2c/BRIEF.md`).

| Batch | Ids | Domains | Agent | Status |
|---|---|---|---|---|
| 2d-S single_congress | 103–115 | ean, aaic.alz, auanet, aao, rsna, chestnet, bofas, bpna, acc, asn-online, asahq, ueg, baaps | `w2d-S` | first scrape clean, remediator running (aao 106 inactive: 403 on runner) |
| 2d-A uk_static_hi | 116–122 | bssh, vascularsociety, baus, his, bbts, associationofbreastsurgery, basl | `w2d-A` | building |
| 2d-B uk_static_lo | 123–129 | endocrinology (Society for Endocrinology), bsir, bmfms, brit-thoracic, rheumatology, bapm, sbns | `w2d-B` | reviewed · registered pending first scrape (CI group M = 124–129); endocrinology 123 blocked (Cloudflare runner + home) — not registered, id reserved |
| 2d-D js_browser_first | 130–133 | bsg, boa, escrs, ics | `w2d-D` | first scrape clean, remediator running |
| 2d-C1 intl_multi | 134–138 | eular, pcronline, siu-urology, eshre, nihr | — | queued (after first gate) |
| 2d-C2 intl_multi | 139–143 | hematology (ASH), aan, aad, cns, augis | — | queued |
| 2d-E commercial_hold | 144–146 | iscmedical, medical-interviews, pastest | — | owner call: commercial course shops |

Excluded: rcsed.ac.uk (already source 28) · jpmorgan.com (investor conference, not CPD) ·
digital-transformation.hee.nhs.uk (programmes, not dated events).

Gate per batch (unchanged from 2c): harness twice → register rows (active) → first scrape
(`main.py --run-now --sources ...`) → remediator → audit → null-audit < 10 % → CI groups
(≤ 10 sources per job) in BOTH matrices → cloud run green.
CI groups (actual, S+D): K = 103–105,107–113 · L = 114,115,130–133 (aao 106 inactive, left out like RCoA 40 and BIASP 72). Batch B: M = 124–129. Groups for A/C follow at their registration (N onward).

## Cloud probe (run 39672930702, 2026-10-21) — `../probes/wave2d.json`
41/44 cleared. Not cleared: **aao.org** (403 Forbidden on both URLs → blocked, register inactive) · **endocrinology.org** (Cloudflare "Just a moment" challenge, 19 s, never cleared → build if home IP clears, register inactive, retry from runner) · **nihr.ac.uk** (CloudFront "request could not be satisfied" → WAF/geo refusal; C1 agent to treat as blocked unless an alternative host works).

## Post-wave follow-ups (Commander-owned, after the gate)
- **single_congress family fix:** 7/13 batch-S sites needed the same `parse_place` hook ("Venue, City, Country") and several hit listing-path date gaps; full evidence in `_family_gaps_single_congress.md` (12 sections). One careful change to `single_congress.py` + regression on 3 live single-congress sources (89–102) + its tests; then retire the duplicated hooks.
- **UK region map consolidation:** a dozen extractors carry their own place→region table (`_UK_REGIONS` / `_UK_PLACES`); create a neutral `extractors/uk_regions.py` and migrate. Per-source modules never import each other (review found baaps→rcpath and bsg→ems_calendar; both replaced with local copies during the wave).
- **Relevance gates:** BOA and BAAPS calendars list third-party promoter events; both now drop off-topic rows (Commander-approved 2026-10-21) and log dropped titles. Watch CI logs for false drops.
- **Cross-source duplicates:** BMFMS (125) and BAPM (128) both list "Beyond the CTG", the Perinatal Symposium and the BICS conference under different URLs; `source_url` is the only dedupe key, so both rows publish. Needs a general design (title+date match across sources in the directory view or a scraper-side canonical key), not a per-source hack. Likely already affects older society pairs.
- **Reviews on disk:** `_review_S.md`, `_review_D.md` (reviewer agents, fresh eyes, pre-registration).

## Gate log
- 2026-10-21 S+D registered (`df28bad`), first scrape local: 16/16 success, 0 errors, 86 inserted (85 live). Null-audit: start_date 0 %, specialty 0 %, description 9.4 %, city 30.6 % (online rows), priced 36/85 with 328 tiers; event_type 40 conference / 24 course / 21 workshop. Remediator + audits running; cloud gate run after.
- 2026-10-21 B registered (`6c8533d`), first scrape local: 6/6 success, 0 errors, 75 inserted; promoter gates dropped 3 rows (2 scientexconference Paris rows on BMFMS, 1 on SBNS). Security hardening `38b6fb1` (+ hop-validated fetch round pending). Remediator + audits running.
