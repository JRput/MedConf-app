# Mission board — CI health, November 2026 (opened 2026-11-20)

Owner: "run tickets 1-3, and review and fix the scrape sources which are failing so they continue to work from now on." Report that opened it: scrape-daily red 12/12 nights since 9 Nov (ARRS 78 member-gated; EAU 50 listing broken since 16 Nov; EADV 81 runner-challenged nightly; one-off site hiccups), all five daily crons starting 7–9 h late, `test_blocked_status.py` writing fake ARVO rows into production `scraper_logs` (278 rows).

**Baseline:** main `d4ba4d0`, tree clean apart from the owner's files. Foreman = session model; worker tickets `model: sonnet`; PRINCIPLES arm OFF.

| id | tier | status | write set | evidence |
|---|---|---|---|---|
| T1 test leak | foreman | PENDING | `medconf-scraper/test_blocked_status.py`; delete the 278 `arvo.example` rows from `scraper_logs` | |
| T2 EAU 50 listing rebuild | sonnet | PENDING | `medconf-scraper/extractors/uroweb.py`, `medconf-scraper/test_uroweb*.py`, `medconf-scraper/test_fixtures/uroweb_*` | |
| T3 cron slots | foreman | PENDING | `.github/workflows/{scrape-daily,remediator-daily,fire-specialty-alerts,fire-reminders,fire-moderation-digest}.yml`, CLAUDE.md cron lines | |
| T4 failing sources review | foreman | PENDING | diagnosis of EADV 81, ESHRE 137, AAP 147, EANS 159, ABN 160, FACE 164, Advance HE 53; fixes as separate tickets if code | |

## Log
- 2026-11-20 15:00 UTC — board opened.
