# Mission board — CI health, November 2026 (opened 2026-11-20)

Owner: "run tickets 1-3, and review and fix the scrape sources which are failing so they continue to work from now on." Report that opened it: scrape-daily red 12/12 nights since 9 Nov (ARRS 78 member-gated; EAU 50 listing broken since 16 Nov; EADV 81 runner-challenged nightly; one-off site hiccups), all five daily crons starting 7–9 h late, `test_blocked_status.py` writing fake ARVO rows into production `scraper_logs` (278 rows).

**Baseline:** main `d4ba4d0`, tree clean apart from the owner's files. Foreman = session model; worker tickets `model: sonnet`; PRINCIPLES arm OFF.

| id | tier | status | write set | evidence |
|---|---|---|---|---|
| T1 test leak | foreman | DONE (`b4795cb`; 19 tests; 278 rows deleted, 72 real ARVO logs kept) | `medconf-scraper/test_blocked_status.py`; delete the 278 `arvo.example` rows from `scraper_logs` | |
| T2 EAU 50 listing rebuild | sonnet | DONE_WITH_CONCERNS (env only) → foreman: diff read, 7 tests, suite 1430, live run 42 shells / 9 inserted / 5 updated, 49 active rows | `medconf-scraper/extractors/uroweb.py`, `medconf-scraper/test_uroweb*.py`, `medconf-scraper/test_fixtures/uroweb_*` | |
| T3 cron slots | foreman | DONE (`b4795cb`; 01:41 / 02:29 / 03:47 / 07:07 / 08:11 UTC; YAML parsed; watch 21–22 Nov) | `.github/workflows/{scrape-daily,remediator-daily,fire-specialty-alerts,fire-reminders,fire-moderation-digest}.yml`, CLAUDE.md cron lines | |
| T4 failing sources review | foreman | DONE: EADV 81 fixed (bare host; live 7 shells, 1 inserted); ESHRE 137 transient; runner-challenged set unchanged (identification = owner's call); ARRS 78 owner item | diagnosis of EADV 81, ESHRE 137, AAP 147, EANS 159, ABN 160, FACE 164, Advance HE 53; fixes as separate tickets if code | |

## Log
- 2026-11-20 15:00 UTC — board opened.
- 2026-11-20 15:40 UTC — T1 + T3 pushed. T4 diagnosis: ESHRE 137 transient (local run 9 shells, 1 inserted); EADV 81 blocked from the runner AND locally (httpx 403, Cloudflare challenge in Playwright after 20 s; last success 13 Nov) → site hardened, not runner-specific; AAP 147 / EANS 159 / ABN 160 / FACE 164 / Advance HE 53 intermittent runner challenges with a success every 1–3 nights (data current). Any identification change (user agent) is the owner's call.
- 2026-11-20 15:50 UTC — T2 landed on main; EADV moved to eadv.org (www host 403s everything since 14 Nov); scrape-daily dispatched by hand as the gate. Open: ARRS 78 (member-gated), AAP 147 / EANS 159 / ABN 160 / FACE 164 / Advance HE 53 intermittent runner challenges, cron delay watch 21–22 Nov. MISSION CLOSED pending the gate run.
