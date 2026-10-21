# Wave 2d — static HTML + unknown-platform sources (opened 2026-10-21)

Source of truth for ids/slugs/recon: `plan.json`. Probe input: `candidates.json`
(`probe-cloud-access.yml`). Brief: `BRIEF.md` (delta over `../wave2c/BRIEF.md`).

| Batch | Ids | Domains | Agent | Status |
|---|---|---|---|---|
| 2d-S single_congress | 103–115 | ean, aaic.alz, auanet, aao, rsna, chestnet, bofas, bpna, acc, asn-online, asahq, ueg, baaps | `w2d-S` | building |
| 2d-A uk_static_hi | 116–122 | bssh, vascularsociety, baus, his, bbts, associationofbreastsurgery, basl | `w2d-A` | building |
| 2d-B uk_static_lo | 123–129 | endocrinology (Society for Endocrinology), bsir, bmfms, brit-thoracic, rheumatology, bapm, sbns | `w2d-B` | building |
| 2d-D js_browser_first | 130–133 | bsg, boa, escrs, ics | `w2d-D` | building |
| 2d-C1 intl_multi | 134–138 | eular, pcronline, siu-urology, eshre, nihr | — | queued (after first gate) |
| 2d-C2 intl_multi | 139–143 | hematology (ASH), aan, aad, cns, augis | — | queued |
| 2d-E commercial_hold | 144–146 | iscmedical, medical-interviews, pastest | — | owner call: commercial course shops |

Excluded: rcsed.ac.uk (already source 28) · jpmorgan.com (investor conference, not CPD) ·
digital-transformation.hee.nhs.uk (programmes, not dated events).

Gate per batch (unchanged from 2c): harness twice → register rows (active) → first scrape
(`main.py --run-now --sources ...`) → remediator → audit → null-audit < 10 % → CI groups
(≤ 10 sources per job) in BOTH matrices → cloud run green.
Planned CI groups: K = 103–112 · L = 113–122 · M = 123–132 · N = 133+ (set at registration).
