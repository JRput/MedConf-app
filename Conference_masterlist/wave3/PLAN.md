# Wave 3 — masterlist long tail (opened 2026-11-09)

Owner: "go ahead with wave 3, activate hq and command centre foreman". Planner = session model (no Fable/Astra). Workers `model: sonnet`; reviewer `model: sonnet` per batch (as 2d); PRINCIPLES arm OFF.
Baseline: main `c460fdf`, tree clean apart from the owner's untracked reports/JSON files.
Source of truth: `plan.json` (ids 147–158). Probe input: `candidates.json` (12 build + 22 re-probe domains). Brief: `BRIEF.md` (delta over 2c/2d).

| Batch | Ids | Domains | Agent | Status |
|---|---|---|---|---|
| 3-S single_congress | 147–154 | aapexperience, amwc, badannualmeeting, bsped, digitalhealthrewired, rheumatology (ACR), thoracic (ATS), congress.eular | `w3-S` | dispatched |
| 3-M multi_event | 155–158 | britishcardiovascularsociety, events.england.nhs.uk, imcas, ors | `w3-M` | dispatched |
| re-probe (no build) | — | 22 parked/blocked domains (astro, heart, himss, esska, eans, abn, uscap, face, bask, fci, phemcast, mata, aao, endocrinology, nihr, rcoa, biasp, wfns.org, esge, ese, congress.ehaweb, reviseradiology) | probe workflow | running |
| owner's call | — | doctorsacademy (commercial course shop), harleyacademy/skinviva (commercial aesthetics), medicalprotection (login) | — | not built |

Gate per batch (unchanged): harness twice → review → register rows (active) → first scrape → remediator → audit → null-audit < 10 % → CI group P (and Q if needed) in BOTH matrices + website societies taxonomy (`check_taxonomy.py`) → cloud run green.

## Log
- 2026-11-09 — board created; probe + two builders dispatched.
