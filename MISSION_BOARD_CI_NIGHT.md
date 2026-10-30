# Mission board — CI-night follow-ups (2026-10-30)

Owner decision 2026-10-30: "ok proceed - activate hq and command centre foreman and deploy subagents" on the five items from the CI-night check (findings: end of MISSION_BOARD_COVERAGE.md).

**Baseline:** main `1306b53`; `git status --porcelain` = the two long-standing modified files only (`Conference_masterlist/wave1d/mddus.json`, `reports/remediation/learned_patterns.json` — never commit). Foreman = session model; workers explicit `model: sonnet`; verifier `model: opus`; PRINCIPLES arm OFF (no flag file) → unchanged ticket contract, no record/complete.

**Order after the workers:** foreman deterministic checks (full scraper suite `./.venv/bin/python -m pytest -q --ignore=test_api.py`, YAML parse, T2 dry run) → backstop commit → blind verifier (opus) on T1 + T2 + T5 → fix wave if needed → push main → T2 `--apply` (production write, owner-approved in the "proceed") → `coverage_report.py --update-baseline` → commit/push → watch the next night.

## Tickets

| id | tier | status | write set | evidence |
|---|---|---|---|---|
| T1 city fixer context rule | sonnet | DONE_WITH_CONCERNS → foreman re-ran 149 passed; diff reviewed (online guard, venue_name, prefix windows 160 chars, footer zone 15 %/4000, postcode mapping gated, "S" dropped; `heuristic_known_city` gone) | `medconf-scraper/remediator/fixers/venue.py`, `medconf-scraper/test_city_fixer.py` (new) | — |
| T2 repair script (dry-run default) | sonnet | DONE_WITH_CONCERNS → foreman re-ran 7 tests + dry run: candidates 54, keep 4 (1537 region London, 2164 venue Edinburgh, +2), null 50, archived-skipped 18; concern (2844 FAMUS/FUSIC absent) = expected, its city was never heuristic-written | `medconf-scraper/tools/repair_heuristic_city.py` (new), `medconf-scraper/test_repair_heuristic_city.py` (new) | — |
| T3 workflows: cron minutes + budgeted audit job | sonnet | DONE_WITH_CONCERNS → foreman re-parsed YAML ok; diffs = cron hunks + audit budget loop + AUDIT_DAY upload path; stale header comments (02:00/04:00) to be refreshed by the foreman in the docs pass | `.github/workflows/scrape-daily.yml`, `.github/workflows/remediator-daily.yml` | — |
| T4 ASH 139 listing sentence | sonnet | DONE_WITH_CONCERNS → annual meeting parses again (live probe: 2026-12-12→15, New Orleans, hybrid); fixture `fixtures/ash_meetings_2026-10-30.html` 93 KB; the four regional "Highlights of ASH" programmes are still lost (headings + line layout changed) → **T4b dispatched to the same worker** | `medconf-scraper/extractors/hematology.py`, `medconf-scraper/test_hematology.py` (new), optional fixture under `medconf-scraper/test_fixtures/` | — |
| T5 IDWeek 55 verified-empty between editions | sonnet | DONE (foreman re-ran: 22 passed; diff = reset + two verified_empty branches, 11 lines) | `medconf-scraper/extractors/idweek.py`, `medconf-scraper/test_idweek.py` (new) | — |
| V1 blind verifier (T1 + T2 + T5) | opus | PENDING | none (read-only) | — |

Write sets are pairwise disjoint (no manifests/lockfiles touched) → parallel dispatch.

## Log
- 2026-10-30 ~13:50 UTC — board created; T1–T5 dispatched in one wave.
- 2026-10-30 ~13:35 UTC — T5 DONE; foreman check green (`test_idweek.py` + `test_single_congress.py` 22 passed). Worker concern noted: a homepage that keeps "IDWeek 20xx" but drops the date line for another reason also reads as verified-empty (reason text names the year).
- 2026-10-30 ~13:40 UTC — T1 and T3 DONE_WITH_CONCERNS; foreman checks green. T1 concern = fewer rows get a heuristic city (intended; `_html_place` + LLM still run). T3 concerns = header comments still say 02:00/04:00 (foreman docs pass), rotation covers ~17–36 sources/night (full sweep in ~4–8 nights), a `timeout` kill prints non-PASS.
- 2026-10-30 ~13:50 UTC — T2 and T4 DONE_WITH_CONCERNS; foreman checks green. T4b (heading aliases + structured-line layout for the four regional programmes) sent to ci-night-T4. Full suite running.
