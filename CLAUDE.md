# MedConf — Project Brain

> Auto-loaded by Claude Code at session start. This file is the single source of truth for project context, conventions, and how-to-run. Keep it short and current — link out to deeper docs rather than duplicate them here.

> **Production state (2026-10-24):** **Website LIVE on Vercel since 2026-10-24 (see the DEPLOYED paragraph below). REGISTRATION GATE LIVE since 2026-10-24 evening:** the directory list (`/conferences`), `/societies`, search and `/api/directory` require a signed-in user (middleware + in-page checks, `?next=` preserved); the homepage is a public front door (counts, closing-soon with relative deadlines, 6 visible + 6 blurred this-month rows with a sign-in card, specialty/society tiles that open the sign-in gate); event pages are public teasers with a locked panel. **Database layer closed too (Phase 2b applied):** anon has no read on `conferences`/`pricing_tiers`/`course_sessions`/`scraper_sources`/community tables, no SELECT on `directory_events`, no EXECUTE on `directory_facets`; anonymous pages read ONLY `home_preview()`, `event_preview(id)` and `sitemap_events()` (SECURITY DEFINER, bounded; `sitemap_events` is paged in 1000-row chunks — PostgREST cap). Board: MISSION_BOARD_ACCESS_GATE.md. Follow-up: remove the `TODO(access-gate)` PGRST202 fallbacks (HQ backlog). **Sign-in flow hardened 2026-10-24 (MISSION_BOARD_SIGNIN.md):** `/auth/verify?email&reason` shows the address, a Resend button (60 s cooldown, anti-enumeration copy) and the real 1-hour expiry; login errors are mapped (never raw Supabase text) with a resend path for unconfirmed accounts; the sign-up intent `next` survives verification/onboarding via a 1 h `mc_next` cookie; new-user verification links land on `/onboarding?next=`; sign-out returns to `/`. **Auth emails:** six templates in `supabase/templates/` use device-independent `token_hash` links (`EMAIL_TEMPLATES.md`); upload them + custom SMTP with `scripts/supabase_auth_setup.py` (needs an `sbp_` token in the shell) or paste in the dashboard. **Custom SMTP LIVE 2026-10-26:** Supabase Auth now sends through Gmail SMTP (`smtp.gmail.com:587`, sender `MedConf <hellomedicon@gmail.com>`, Gmail App Password; Supabase email rate limit raised 2 → 20/h, Gmail cap ≈500/day) and the six branded templates + subjects are uploaded — both pushed with `scripts/supabase_auth_setup.py` through the Management API (token scoped to this project only: Auth Config + Project Settings read-write, revoked after use; secrets held in the macOS Keychain, never in files). Run the script with `SSL_CERT_FILE="$(medconf-scraper/.venv/bin/python -c 'import certifi;print(certifi.where())')"` — `/usr/local/bin/python3` has no CA bundle and fails with CERTIFICATE_VERIFY_FAILED. Live smoke 2026-10-26: recovery → owner and sign-up confirmation → a non-team plus-address both accepted (`confirmation_sent_at` set; previously `email_address_not_authorized`). Still before public launch: Auth CAPTCHA (Turnstile) + per-IP limits; Resend once a domain exists. **Pricing accuracy fix 2026-10-27 (MISSION_BOARD_PRICING_FREE.md, commit `5d5f270`):** ELCC 2027 and 108 other events showed "Free" from a lone £0 tier — the remediator's `free_event` rule fired on a "Press Representatives | Free of charge" table row before looking for prices, the ESMO parser only knew enumerated row labels, and nothing re-detailed rows whose fees were published later. Now: table-driven ESMO registration parser (timeframe-first ` · ` labels, deadlines → `early_bird_deadline`); per-source opt-in `REFRESH_DETAIL_WHEN_NO_PRICING_DAYS` (ESMO = 7, 15 rows/run, non-destructive update where only `_evidence` keys may overwrite); remediator free verdict only with no price signal (`remediator/signals.py`) and the trigger sentence logged; audit SUSPECT "Stored as free but page shows fee amounts"; `medconf-scraper/tools/audit_zero_tiers.py` evidence audit (dry-run reports in `reports/pricing/`, guarded `--apply`). Follow-ups: ERS member-free/non-member-paid tiers; ESMO course typing. **Wave 2d delivered 2026-10-22 — 141 registered sources, 141 − 6 inactive/blocked = 41 new active (ids 103–143; CI groups K–O; see `Conference_masterlist/wave2d/PLAN.md`).** Password reset flow (`/auth/forgot-password` → email link → `/auth/reset-password`) shipped 2026-10-20 together with a fix to `/auth/callback`, which now writes session cookies onto the redirect (verified sign-ups land signed in on /onboarding) — see MISSION_BOARD_AUTH.md; owner dashboard steps in EMAIL_SETUP_GUIDE.md. Community contributions (add-info + moderated submissions) shipped 2026-10-18 — see MISSION_BOARD_CONTRIBUTIONS.md. **100 active sources before wave 2d (141 after)** — wave 2c batch 4 (85–102, CI groups I/J, gated 2026-10-14): ESAIC (85), Euretina (86), AASLD (87), BESS (88) and 14 one-event congress sites on the `single_congress` family — UKIO (89), DDW (90), ECTRIMS (91), EFORT (92), EAPS (93), ESPID (94), PAS (95), ACOG (96), ESCMID (97), CROI (98), ECR/ESR (99), CCR London (100), NHS ConfedExpo (101), ViVE (102); wave 2c batch 3 (75–84, CI group H, gated 2026-10-13): AAOS (75), The Ultrasound Site (76), Endocrine Society (77), ARRS (78), BSCCP (79), CRF (80), EADV (81), ATACC (82), Interface Aesthetics (83), BDIAP (84); ESTRO (19) lists congresses from estro.org's Power Pages events API (the portal renders /Congresses client-side; 2026-10-16); wave 2c batch 1 (60–74 minus BIASP 72 parked: runner IPs challenged; CI group G, gated 2026-10-09): ERS (60), BSGE (61), BCIS (62), FDI (63), ECCO (64), EASL (65), BAPRAS (66), ESICM (67), APM (68), ERA (69), EUSEM (70), Derma Medical (71), BIA (73), SAM (74) — most are constants-only subclasses of the `wordpress_generic` family; wave 2a/2b (46–59, CI group F, gated 2026-10-06): BAETS (46), AANS (47), AAGL (48), ESP (49), EAU/uroweb (50), EANM (51), SCCM (52), Advance HE (53), IFOS (54), IDWeek (55), ISUOG (56), IHI (57), BSH (58), ACEP (59); plus the original 44 — RCGP (1), RCSEng events (2), RSM (3), RCP (4), RCSEng courses (5), RCEM × 3 (6/7/8), RCOG × 2 (9/10), RCR × 2 (11/12), BOPA (13), BTOG (14), ASCO × 2 (15/16), ESMO (17), AACR (18), ESTRO (19), SABCS (20), ESGO × 2 (21/22), SITC (23), plus masterlist wave 1a: ALSG (24), RCPSG (25), RCPath (26), RCPsych (27), RCSEd (28), Resus Council UK (29), wave 1b: RCPE (30), RCPCH (31), RCOphth (32), FPH (33), FOM (34), FPM (35), ESC (36), ACPGBI (37), ASGBI (38), CoSRH (39), FICM (41), ARVO (42), IAS (43), MDDUS (44), MDU (45); RCoA (40) registered but inactive (Cloudflare blocks runner IPs) — scale-up plan in [MISSION_BOARD.md](MISSION_BOARD.md). Product has expanded from a UK CPD directory into a global oncology-heavy directory. Four daily crons on GitHub Actions: **02:00 UTC** scrape matrix (model probe job + 15 grouped workers A–O), **03:00 UTC** specialty alerts (in-app), **04:00 UTC** remediator (all sources), **08:00 UTC** saved-event reminders. Multi-currency in production (USD/EUR/HKD/SGD alongside GBP). Repo: https://github.com/JRput/MedConf-app · **Active Supabase project:** `zcpszfbmvfylicpxgsfc` (eu-west-1, hotmail org). **For next-session handoff** see [memory/project_pending_work.md](file:///Users/Sushil/.claude/projects/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/memory/project_pending_work.md).
>
> **LLM models — fallback chains** (rotated 2026-10-21 after NVIDIA retired `nemotron-3-super-120b-a12b`; the chain was first built 2026-09-20 after NVIDIA retired every configured model on 2026-08-26 and calls failed silently for 25 days): text chain = `nvidia/nemotron-3.5-lightning-30b-a3b` → `meta/muse-glimmer-30b` → `openai/gpt-oss-20b`; vision chain = `meta/muse-glimmer-30b` → `nvidia/nemotron-3.5-super-vl-120b-a12b` → `meta/llama-3.2-11b-vision-instruct`. `llm_client.chat_completion()` advances past any model that 404s/410s. `probe_models.py` runs as the first job of the daily scrape — whole chain dead = red run. Defaults live in `config.py`; override with `KIMI_MODEL_CHAIN` / `KIMI_VISION_MODEL_CHAIN`.
>
> **DEPLOYED 2026-10-24 — production at https://medconf.vercel.app** (Vercel project `medconf`, team `jaikishrajput-gmailcoms-projects`, Git-linked to `JRput/MedConf-app` with `main` as the production branch → every push to main auto-deploys; root directory `medconf-website`, Node 22.x, env = the two public Supabase vars only). Board: MISSION_BOARD_DEPLOY.md. Supabase Auth Site URL `https://medconf.vercel.app` + redirect allowlist (`https://medconf.vercel.app/**`, `https://medconf-*-jaikishrajput-gmailcoms-projects.vercel.app/**`) confirmed set 2026-10-26; custom SMTP live (Gmail, see above). Owner steps still open: custom domain, then Resend. Local dev still `PORT=3000 npm run dev`. Fixture directory data (`?fixture=1`, missing-view fallback) is unreachable in production unless `NEXT_PUBLIC_DIRECTORY_FIXTURE` is set (`src/lib/directory-source.ts` `fixtureAllowed()`, 2026-10-24). **Website redesigned 2026-10-03 (Mission W):** light/dark design system, server-side directory (`directory_events` view), `/societies`, `/calendar` (personal). Design tile at `/design`. DB migrations: `medconf-scraper/apply_migration.py`.

---

## 1. Identity & Aim

**MedConf** is a web platform that consolidates medical conferences, talks, and CPD (Continuing Professional Development) events into a single searchable directory. UK-first origin, but now covers international flagship oncology conferences too (ASCO, ESMO, AACR, ESTRO, SABCS, ESGO, SITC).

- **Target users:** NHS consultants, GPs, registrars, fellows, medical students, nurses & allied health.
- **Core value:** eliminates fragmented hunting across organiser sites, society newsletters, and notice boards. Users find CPD-accredited events and track their points obligations in one place.
- **Out of scope:** booking. MedConf redirects users to organisers' own sites for registration.
- **Status:** PRD v1.0 (Feb 2026, Draft). Targets at 6 months: 500+ users, 200+ active listings, 95%+ data accuracy, 15%+ organiser-self-managed.
- **Future phases:** organiser self-service listings → paid promotional listings for smaller events → expansion beyond UK.

Authoritative documents:
- [MedConf_PRD.md](MedConf_PRD.md) — product requirements
- [MedConf_Frontend_Build_Guide.md](MedConf_Frontend_Build_Guide.md)
- [MedConf_Agentic_Scraper_Build_Guide.md](MedConf_Agentic_Scraper_Build_Guide.md)
- [MedConf_Flow_Diagrams.jsx](MedConf_Flow_Diagrams.jsx)

---

## 2. Architecture (3 components → 1 Supabase DB)

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  medconf-scraper/        │  upsert │                          │
│  Python · Llama 3.3 70B  │────────►│      Supabase            │
│  Playwright + httpx      │         │  Postgres + Auth + RLS   │
│  GitHub Actions cron     │         │                          │
└──────────────────────────┘         │  conferences             │
         ↓ (Tier 2)                  │  pricing_tiers           │
┌──────────────────────────┐         │  course_sessions         │
│  remediator/             │────────►│  scraper_sources/logs    │
│  7 fixers + vision LLM   │         │  user_profiles           │
│  audit gate              │         │  saved_conferences       │
└──────────────────────────┘         │  notifications           │
                                     │  user_reminders          │
┌──────────────────────────┐  reads  │  notification_preferences│
│  medconf-website/        │◄────────│                          │
│  Next.js 16 · React 19   │         └──────────────────────────┘
│  Tailwind v4 · @supabase │
└──────────────────────────┘
```

### 2.1 `medconf-scraper/` — Two-phase scraper with per-source extractors
**Replaced the original agentic LLM loop in Phase 6.** Listing pages are now walked deterministically; only soft fields (description, specialty) involve the LLM, with heuristic classifiers as backstops.

| File | Role |
|---|---|
| [main.py](medconf-scraper/main.py) | Entry point; `--run-now [--source N]` for cloud workers, plain `main.py` starts APScheduler (legacy local-only) |
| [scheduler.py](medconf-scraper/scheduler.py) | Loops all active sources; runs multi-rule archival (expired / undated-past / unseen-14d) |
| [scraper.py](medconf-scraper/scraper.py) | `scrape_source()` — incremental hash decision: fast-skip unchanged events, slow-path for new/changed |
| [llm_agent.py](medconf-scraper/llm_agent.py) | `list_shells()` (Phase A — DOM walk) + `extract_detail_for_shell()` (Phase B — per-source extractor) |
| [browser.py](medconf-scraper/browser.py) | `get_event_cards_paginated()` — walks `?page=1..N` with auto-detection, dedup |
| [extractors/](medconf-scraper/extractors/) | 26 per-source modules (rcgp/rcseng/rsm/rcp/rcem/rcog/rcr/bopa/btog/asco/esmo/aacr/estro/sabcs/esgo/sitc/alsg/rcpsg/rcpath/rcpsych/rcsed/resus/…). Shared helpers: `specialty_classifier.py` (~40 title→specialty rules), `abstract_classifier.py`, `pricing_tables.py` (universal plain-number fee-table parser — try first before rolling a bespoke one), `vision.py` for image-based fees. `fallback.py` is LLM-only for unflagged sources |
| [extractors/PLAYBOOK.md](medconf-scraper/extractors/PLAYBOOK.md) | Four-step onboarding protocol for a new source |
| [validator.py](medconf-scraper/validator.py) | Schema/sanity checks + junk-label filter + footnote stripping |
| [remediator/](medconf-scraper/remediator/) | Post-scrape fixer + audit gate. 7 fixers; explorer follows same-site registration pages, external organiser sites (two hops), microsite nav (General Info/Abstracts), PDFs, image fee tables (vision), JS-rendered fee pages; matrix fee grids; row rotation via `remediation_attempted_at` under a 600 s per-source budget; audit flags evidence of misses (fees/venue/call-for-papers on page but not stored) — see PLAYBOOK "Coverage checklist" |
| [database.py](medconf-scraper/database.py) | Supabase ops. `archive_stale_conferences` has a **source-health guard** — won't archive if source hasn't had a successful scrape in the window |

**Current LLM models** (fallback chains, 2026-09-20):
- Text chain: `nvidia/nemotron-3.5-lightning-30b-a3b` → `meta/muse-glimmer-30b` → `openai/gpt-oss-20b` (see [llm_client.py](medconf-scraper/llm_client.py)).
- Vision chain: `meta/muse-glimmer-30b` → `nvidia/nemotron-3.5-super-vl-120b-a12b` → `meta/llama-3.2-11b-vision-instruct`. ⚠ Only verified on a synthetic fee table — re-check on the next real image-based fee page (rotation log in `vision.py`).
- Check what's alive: `./.venv/bin/python probe_models.py`. `/v1/models` lists dead models — only a real completion proves liveness.
- Rotation runbook: [memory/project_kimi_eol.md](file:///Users/Sushil/.claude/projects/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/memory/project_kimi_eol.md).

⚠ **APScheduler caveat (HQ LESSONS #1):** APScheduler `BlockingScheduler` is unreliable on macOS. **Production uses GitHub Actions cron, not APScheduler.** The local APScheduler path stays for dev convenience only.

### 2.2 `medconf-website/` — Next.js 16 frontend
- **Stack:** Next 16.1.6, React 19.2.3, Tailwind v4, `@supabase/ssr` 0.8 + `@supabase/supabase-js` 2.95, `lucide-react` icons.
- **Routes:** `/` home (public front door), `/conferences` list+filters (**sign-in required since 2026-10-24**), `/conferences/[id]` detail (public teaser; full page when signed in), `/societies` (sign-in required), `/dashboard`, `/dashboard/notifications`, `/saved`, `/settings`, `/onboarding` (all protected), `/auth/{login,signup,verify,setup-profile,callback,forgot-password,reset-password}`.
- **Route guard:** `src/middleware.ts` + `src/lib/auth/gate.ts` — `isGatedPath` = PROTECTED_PATHS (`/saved`,`/settings`,`/dashboard`,`/onboarding`,`/calendar`,`/submit`,`/admin`) + `/conferences` (list) + `/societies`; signed-out → `/auth/login?next=<path>` (validated by `safeNextPath`); profile-completion gate only on the personal pages (`isProfileGatedPath`). `/api/directory` gates itself (401, `private, no-store`). The list pages also check in-page (defence in depth).
- **Hooks:** [useConferences.ts](medconf-website/src/hooks/useConferences.ts), [useSaved.ts](medconf-website/src/hooks/useSaved.ts), [useAuth.ts](medconf-website/src/hooks/useAuth.ts).
- **Lib:** [supabase.ts](medconf-website/src/lib/supabase.ts), [types.ts](medconf-website/src/lib/types.ts).
- **Components:** `ConferenceCard`, `FilterPanel`, `SearchBar`, `PricingTable`, `CPDBadge`, `SaveButton`, `Navbar`, `Footer`.

### 2.3 Supabase
- Schema: [supabase_schema.sql](supabase_schema.sql) is the hand-maintained source of truth. `supabase/migrations/` files are frozen at Feb 2026 and DO NOT reflect current schema (course_sessions, user_reminders, notifications, is_flagship, is_on_demand, abstract_deadline_note, pricing_tiers.currency all missing). **Do NOT run `supabase db reset` against prod — it would nuke the live schema.** Consolidation is a pending task.
- Tables: `conferences`, `pricing_tiers`, `course_sessions`, `scraper_sources`, `scraper_logs`, `user_profiles`, `saved_conferences`, `notification_preferences`, `notifications`, `user_reminders`, `community_contributions`, `community_facts`, `community_tiers`.
- RLS: ON for all. **Since 2026-10-24 reads on `conferences` (archived = FALSE), `pricing_tiers`, `course_sessions`, `scraper_sources` and published community facts/tiers are `TO authenticated` only; anon reaches directory data solely through `home_preview()`, `event_preview(id)`, `sitemap_events()`** (migrations `20261024000001` functions + `20261024000002` revoke; rollback `20261024000002_rollback.sql`). User-data is owner-only via `auth.uid()`. Scraper tables service-key only.

---

## 3. How to Run

### Frontend dev server
```bash
cd medconf-website
PORT=3001 npm run dev      # 3000 may be in use locally
# → http://localhost:3001
```

### Scraper — production path (GitHub Actions, automated)
- Daily at 02:00 UTC via `.github/workflows/scrape-daily.yml`
- Manual trigger from https://github.com/JRput/MedConf-app/actions (or `gh workflow run scrape-daily.yml --repo JRput/MedConf-app`)
- Each source runs on its own cloud worker in parallel

### Scraper — local dev paths
```bash
cd medconf-scraper
./.venv/bin/python main.py --run-now                     # all active sources
./.venv/bin/python main.py --run-now --source 18         # just AACR
python -m remediator --source 22                         # fix ESGO gaps post-scrape
python -m remediator.audit --source 20                   # gate check for SABCS
```

### Required environment
- **Scraper**: copy [.env.example](medconf-scraper/.env.example) → `.env`. Vars: `KIMI_API_KEY`, `KIMI_BASE_URL` (default OK), optional `KIMI_MODEL_CHAIN` / `KIMI_VISION_MODEL_CHAIN` (comma-separated; defaults in `config.py`; legacy `KIMI_MODEL` / `KIMI_VISION_MODEL` go first in the chain if set), `SUPABASE_URL`, `SUPABASE_KEY` (service-role), optional `SCRAPER_TIMEOUT_MS` (default 30000).
- **GitHub Actions secrets** ([repo settings](https://github.com/JRput/MedConf-app/settings/secrets/actions)): `KIMI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`. Model chains are set inline in the workflow YAML.
- **Website**: copy [.env.example](medconf-website/.env.example) → `.env.local`. Vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable/anon key, NOT the service-role).

### Daily cron schedule (`.github/workflows/`)
- `scrape-daily.yml` — **02:00 UTC** — `probe-models` job, then 15 grouped jobs A–O (`--sources`), `fail-fast: false`. Keep `remediator-daily.yml` groups identical. A source that yields 0 cards after an anti-bot challenge or a transport outage is recorded as `blocked` / `unreachable` (WARNING, group stays green); 3 consecutive such runs fail the group red (`main.py`, since 2026-10-09).
- `scrape-daily.yml` also runs `coverage-check` (read-only `coverage_report.py`, red only on a coverage regression vs `reports/coverage/baseline.json`) after the groups; `remediator-daily.yml` groups F and G are split into F/F2 and G/G2 (mirrored in `scrape-daily.yml`), plus an advisory `audit-report` job (since 2026-10-27).
- `fire-specialty-alerts.yml` — **03:00 UTC** — batched in-app "N new Cardiology events" per user.
- `remediator-daily.yml` — **04:00 UTC** — runs `python -m remediator --all`. Uploads JSON reports as artifacts.
- `fire-reminders.yml` — **08:00 UTC** — fires saved-event reminders users scheduled from the detail page.
- `fire-moderation-digest.yml` — **09:00 UTC** — expires stale community contributions, leaves one unread `moderation` notification per admin when items await review, logs the placeholder moderator email (`MODERATION_NOTIFY_EMAIL`).
- `enrich-submissions.yml` — every 6 hours (cron `15 */6 * * *`) — fetches the organiser page of each pending community submission (`enrichment_status='waiting'`).
- `remediator-daily.yml` community job (`remediate-community`, source 1000) is **live since 2026-10-23 under safe-fetch mode** (`REMEDIATOR_SAFE_FETCH=1`): every hop address-checked and IP-pinned via `safe_fetch.SafeClient`, no headless browser, no link-following outside the checked client, `Accept-Encoding: identity` with compressed responses refused, PDFs capped at 8 MB while streaming + `%PDF` header + parsed in a child process (20 s, 20 pages, 1 GB address space, no secrets in env), DOCX skipped, vision off, and `organiser_url`/`booking_url`/`source_url` never written for source 1000 (`runner._url_patches_allowed`). Since 2026-10-24 inline `data:` images are dropped too (vision fully off under the flag) and PDF rejects / empty parses are logged with the child's `pdf_child_*` marker. The job runs `test_safe_mode.py` + `test_runner_writes.py` first and can never turn the workflow red. Flag OFF = byte-identical behaviour for scraped sources. Boards: MISSION_BOARD_SAFE_FETCH.md, MISSION_BOARD_SAFE_FETCH_FOLLOWUP.md.
- **Remediator writes are compare-and-swap for ALL sources (since 2026-10-24):** every `_patch_row` update carries the value it read as a precondition (`IS NULL` / `eq`), so an edit made between the remediator's read and its write is never overwritten — the patch is skipped and logged `row changed since read`; `abstract_status` conditions on all three abstract columns; pricing goes through `public.remediator_insert_tiers_if_empty` (row lock, inserts only when the conference has no tiers, never deletes; migration `20261024000000`, applied 2026-10-24). The scraper's own tier replace in `database.py` is not under that lock (HQ backlog).

---

## 4. Active issues / debugging context

The scraper has had several production issues — read these before touching it:
- [medconf-scraper/ISSUES_FIXED.md](medconf-scraper/ISSUES_FIXED.md)
- [medconf-scraper/STUCK_ISSUE_ANALYSIS.md](medconf-scraper/STUCK_ISSUE_ANALYSIS.md) and [STUCK_ANALYSIS.md](medconf-scraper/STUCK_ANALYSIS.md)
- [medconf-scraper/SCRAPER_ANALYSIS.md](medconf-scraper/SCRAPER_ANALYSIS.md)
- [medconf-scraper/DATA_FLOW.md](medconf-scraper/DATA_FLOW.md)
- [RATE_LIMIT_FIX.md](RATE_LIMIT_FIX.md) — Kimi/NVIDIA rate-limit handling
- [EMAIL_SETUP_GUIDE.md](EMAIL_SETUP_GUIDE.md) — Supabase auth email setup

Scraper run logs live in `medconf-scraper/*.log` (RCGP runs especially).

---

## 5. Conventions

- **Money:** `price_gbp DECIMAL(10,2)` (historical column name — not always GBP anymore). `pricing_tiers.currency` (`GBP`/`USD`/`EUR`/`HKD`/`SGD`/`CHF`/`BRL`) is the source of truth. Frontend renders currency-appropriate symbol.
- **Pricing labels:** composite `[Section] · [Category] · [Timeframe]` separated by ` · ` (middot). PricingTable groups band as tabs and timeframe as sub-filter when there are enough tiers. Old dashed formats got normalised in the July pricing overhaul.
- **Email notifications:** NOT implemented. `/settings` shows the toggles as "Coming soon" and disabled. Both cron scripts (`fire_specialty_alerts.py`, `fire_reminders.py`) explicitly say in-app only.
- **Dates:** ISO `YYYY-MM-DD` for conference start/end and abstract deadlines. Timestamps `TIMESTAMPTZ`.
- **Dedupe key:** `conferences.source_url` is unique. If extraction yields no source URL, scraper synthesises one from `name|date|city|venue` MD5 hash (see [scraper.py](medconf-scraper/scraper.py:60-75)).
- **Archival:** expired conferences are archived (`archived = TRUE`), never deleted.
- **Specialty / region:** plain text fields for now; standardise via enum later if needed.
- **Society codes:** `scraper_sources.society` is a SHORT code (acronym or short brand, e.g. `BOA`, `Vascular Society`) shared by every row of one society. It is the filter chip label, the `?society=` URL value and the key of `medconf-website/src/lib/taxonomy/societies.ts`. **Registering a source is not done until the code is in that file** (name, kind, country) — the site falls back to the bare code under "Other", and the daily `taxonomy-check` job in `scrape-daily.yml` fails red until it is added. Check locally: `./.venv/bin/python check_taxonomy.py` (scraper) or `npm run check:societies` (website). Missed on waves 2a–2d (HQ LESSONS #25).

---

## 6. CLAUDE HQ + Memory

This project is an **HQ-managed** project (per `~/.claude/CLAUDE.md`). On any non-trivial work:
1. Load `~/claude-hq/commander/COMMANDER.md`, `LESSONS.md`, and `registry.json` first.
2. Classify the task and pick tools from the registry before starting.

### Memory layers active for this project
- **Auto-memory** (Claude Code's file-based) — `/Users/Sushil/.claude/projects/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/memory/` — persistent across chats automatically. Key files: `MEMORY.md` (index) + topic files.
- **MemPalace** wing `mytalk_conference_app` — verbatim project memory in ChromaDB. Rooms: `medconf_scraper`, `medconf_website`, `supabase`, `skills`, `general`. Config: [mempalace.yaml](mempalace.yaml).

### Useful MemPalace commands
```bash
export PATH="$HOME/Library/Python/3.11/bin:$PATH"
mempalace status                                          # what's filed
mempalace mine "/Users/Sushil/Documents/Documents/IMT2/Side hustle/myTalk_conference app"   # ingest/refresh
mempalace search "abstract deadline" --wing mytalk_conference_app
mempalace wake-up --wing mytalk_conference_app           # session start primer
```

---

## 7. Don't-do list (project-specific)

- Don't reintroduce per-site CSS selectors in the scraper — the agentic LLM design is intentional. Fix prompts and `extraction_instructions` in `scraper_sources` instead.
- Don't run the scraper without `validate_config()` — it will fail silently if env vars are missing in unexpected ways.
- Don't bypass RLS by using service-role keys client-side. Service key is scraper-only.
- Don't `--no-verify` commits or skip hooks (per global rules).
- Don't store credentials in plain text or commit `.env` files. `.gitignore` should catch them; verify before pushing.
