# MedConf — Project Brain

> Auto-loaded by Claude Code at session start. This file is the single source of truth for project context, conventions, and how-to-run. Keep it short and current — link out to deeper docs rather than duplicate them here.

> **Production state (2026-08-14):** **23 active sources** — RCGP (1), RCSEng events (2), RSM (3), RCP (4), RCSEng courses (5), RCEM × 3 (6/7/8), RCOG × 2 (9/10), RCR × 2 (11/12), BOPA (13), BTOG (14), ASCO × 2 (15/16), ESMO (17), AACR (18), ESTRO (19), SABCS (20), ESGO × 2 (21/22), SITC (23). Product has expanded from a UK CPD directory into a global oncology-heavy directory. Four daily crons on GitHub Actions: **02:00 UTC** scrape matrix (23 parallel workers), **03:00 UTC** specialty alerts (in-app), **04:00 UTC** remediator (all sources), **08:00 UTC** saved-event reminders. Multi-currency in production (USD/EUR/HKD/SGD alongside GBP). Repo: https://github.com/JRput/MedConf-app · **Active Supabase project:** `zcpszfbmvfylicpxgsfc` (eu-west-1, hotmail org). **For next-session handoff** see [memory/project_pending_work.md](file:///Users/Sushil/.claude/projects/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/memory/project_pending_work.md).
>
> **LLM models** (rotated 2026-07-31 after NVIDIA revoked our Moonshot grant): text = `meta/llama-3.3-70b-instruct`, vision = `nvidia/nemotron-nano-12b-v2-vl`. Defaults in `config.py` / `vision.py` are set to these — `.env` overrides for local. Backup text model: `nvidia/llama-3.3-nemotron-super-49b-v1`.
>
> **Not yet deployed.** Frontend runs on localhost only (`PORT=3001 npm run dev`). No Vercel/production URL.

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
| [extractors/](medconf-scraper/extractors/) | 20 per-source modules (rcgp/rcseng/rsm/rcp/rcem/rcog/rcr/bopa/btog/asco/esmo/aacr/estro/sabcs/esgo/sitc/…). Shared helpers: `specialty_classifier.py` (~40 title→specialty rules), `abstract_classifier.py`, `pricing_tables.py` (universal plain-number fee-table parser — try first before rolling a bespoke one), `vision.py` for image-based fees. `fallback.py` is LLM-only for unflagged sources |
| [extractors/PLAYBOOK.md](medconf-scraper/extractors/PLAYBOOK.md) | Four-step onboarding protocol for a new source |
| [validator.py](medconf-scraper/validator.py) | Schema/sanity checks + junk-label filter + footnote stripping |
| [remediator/](medconf-scraper/remediator/) | Post-scrape fixer + audit gate. Runs after every scrape. 7 fixers, audit gate with hydrated-pricing second-look, vision LLM for image fees |
| [database.py](medconf-scraper/database.py) | Supabase ops. `archive_stale_conferences` has a **source-health guard** — won't archive if source hasn't had a successful scrape in the window |

**Current LLM models** (rotated 2026-07-31 after NVIDIA revoked our Moonshot grant):
- Text: `meta/llama-3.3-70b-instruct`. Backup: `nvidia/llama-3.3-nemotron-super-49b-v1`.
- Vision: `nvidia/nemotron-nano-12b-v2-vl` (Llama-3.2-90B-Vision returns wordy prose on complex tables → JSON parse fails).
- Rotation runbook: [memory/project_kimi_eol.md](file:///Users/Sushil/.claude/projects/-Users-Sushil-Documents-Documents-IMT2-Side-hustle-myTalk-conference-app/memory/project_kimi_eol.md).

⚠ **APScheduler caveat (HQ LESSONS #1):** APScheduler `BlockingScheduler` is unreliable on macOS. **Production uses GitHub Actions cron, not APScheduler.** The local APScheduler path stays for dev convenience only.

### 2.2 `medconf-website/` — Next.js 16 frontend
- **Stack:** Next 16.1.6, React 19.2.3, Tailwind v4, `@supabase/ssr` 0.8 + `@supabase/supabase-js` 2.95, `lucide-react` icons.
- **Routes:** `/` home, `/conferences` list+filters (**public — no login required**), `/conferences/[id]` detail (public), `/dashboard`, `/dashboard/notifications`, `/saved`, `/settings`, `/onboarding` (all protected), `/auth/{login,signup,verify,setup-profile,callback}`.
- **Route guard:** `src/middleware.ts` — `PROTECTED_PATHS = ['/saved','/settings','/dashboard','/onboarding']`. Directory is intentionally public to match RLS + SEO.
- **Hooks:** [useConferences.ts](medconf-website/src/hooks/useConferences.ts), [useSaved.ts](medconf-website/src/hooks/useSaved.ts), [useAuth.ts](medconf-website/src/hooks/useAuth.ts).
- **Lib:** [supabase.ts](medconf-website/src/lib/supabase.ts), [types.ts](medconf-website/src/lib/types.ts).
- **Components:** `ConferenceCard`, `FilterPanel`, `SearchBar`, `PricingTable`, `CPDBadge`, `SaveButton`, `Navbar`, `Footer`.

### 2.3 Supabase
- Schema: [supabase_schema.sql](supabase_schema.sql) is the hand-maintained source of truth. `supabase/migrations/` files are frozen at Feb 2026 and DO NOT reflect current schema (course_sessions, user_reminders, notifications, is_flagship, is_on_demand, abstract_deadline_note, pricing_tiers.currency all missing). **Do NOT run `supabase db reset` against prod — it would nuke the live schema.** Consolidation is a pending task.
- Tables: `conferences`, `pricing_tiers`, `course_sessions`, `scraper_sources`, `scraper_logs`, `user_profiles`, `saved_conferences`, `notification_preferences`, `notifications`, `user_reminders`.
- RLS: ON for all. Public read on `conferences` (where `archived = FALSE`), `pricing_tiers`, `course_sessions`. User-data is owner-only via `auth.uid()`. Scraper tables admin-only (service key).

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
./.venv/bin/python main.py --run-now                     # all 23 sources
./.venv/bin/python main.py --run-now --source 18         # just AACR
python -m remediator --source 22                         # fix ESGO gaps post-scrape
python -m remediator.audit --source 20                   # gate check for SABCS
```

### Required environment
- **Scraper**: copy [.env.example](medconf-scraper/.env.example) → `.env`. Vars: `KIMI_API_KEY`, `KIMI_BASE_URL` (default OK), `KIMI_MODEL` (default `meta/llama-3.3-70b-instruct`), `KIMI_VISION_MODEL` (default `nvidia/nemotron-nano-12b-v2-vl`), `SUPABASE_URL`, `SUPABASE_KEY` (service-role), optional `SCRAPER_TIMEOUT_MS` (default 30000).
- **GitHub Actions secrets** ([repo settings](https://github.com/JRput/MedConf-app/settings/secrets/actions)): `KIMI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`. `KIMI_MODEL` is set inline in workflow YAML for now.
- **Website**: copy [.env.example](medconf-website/.env.example) → `.env.local`. Vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable/anon key, NOT the service-role).

### Daily cron schedule (`.github/workflows/`)
- `scrape-daily.yml` — **02:00 UTC** — matrix of 23 source jobs, `fail-fast: false`.
- `fire-specialty-alerts.yml` — **03:00 UTC** — batched in-app "N new Cardiology events" per user.
- `remediator-daily.yml` — **04:00 UTC** — runs `python -m remediator --all`. Uploads JSON reports as artifacts.
- `fire-reminders.yml` — **08:00 UTC** — fires saved-event reminders users scheduled from the detail page.

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
