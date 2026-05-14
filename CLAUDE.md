# MedConf — Project Brain

> Auto-loaded by Claude Code at session start. This file is the single source of truth for project context, conventions, and how-to-run. Keep it short and current — link out to deeper docs rather than duplicate them here.

---

## 1. Identity & Aim

**MedConf** is a UK-focused web platform that consolidates medical conferences, talks, and CPD (Continuing Professional Development) events into a single searchable directory.

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
│  Python · Kimi K2.5      │────────►│      Supabase            │
│  Playwright-style browser│         │  Postgres + Auth + RLS   │
│  APScheduler (Sun 02:00) │         │                          │
└──────────────────────────┘         │  conferences             │
                                     │  pricing_tiers           │
┌──────────────────────────┐  reads  │  scraper_sources / logs  │
│  medconf-website/        │◄────────│  user_profiles           │
│  Next.js 16 · React 19   │         │  saved_conferences       │
│  Tailwind v4 · @supabase │         │  notification_preferences│
└──────────────────────────┘         └──────────────────────────┘
```

### 2.1 `medconf-scraper/` — Agentic Python scraper
LLM-driven reasoning loop (no per-site selectors). Each step the LLM picks `navigate` / `extract` / `done`.

| File | Role |
|---|---|
| [main.py](medconf-scraper/main.py) | Entry point; `--run-now` for immediate, otherwise starts scheduler |
| [scheduler.py](medconf-scraper/scheduler.py) | APScheduler weekly cron (Sun 02:00) + archives expired events |
| [llm_agent.py](medconf-scraper/llm_agent.py) | Agentic loop using Kimi K2.5 via NVIDIA OpenAI-compatible API |
| [browser.py](medconf-scraper/browser.py) | Browser controller used by the agent |
| [scraper.py](medconf-scraper/scraper.py) | Orchestrates agent → validate → upsert (dedupe on `source_url`) |
| [validator.py](medconf-scraper/validator.py) | Schema/sanity checks before insert |
| [database.py](medconf-scraper/database.py) | Supabase upsert + archival ops |
| [config.py](medconf-scraper/config.py) | Loads env (KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL, SUPABASE_URL, SUPABASE_KEY) |
| [logger.py](medconf-scraper/logger.py) | Structured logging + `scraper_logs` writer |

⚠ **APScheduler caveat (HQ LESSONS #1):** APScheduler `BlockingScheduler` is unreliable on macOS due to App Nap, sleep/wake, network changes. For production, prefer launchd `StartCalendarInterval` (macOS), systemd timers (Linux), or Task Scheduler (Windows). Add a watchdog (L3) that confirms the run fired by checking `scraper_logs` within minutes.

### 2.2 `medconf-website/` — Next.js 16 frontend
- **Stack:** Next 16.1.6, React 19.2.3, Tailwind v4, `@supabase/ssr` 0.8 + `@supabase/supabase-js` 2.95, `lucide-react` icons.
- **Routes:** `/` home, `/conferences` list+filters, `/conferences/[id]` detail, `/saved`, `/settings`, `/auth/{login,signup,verify,setup-profile,callback}`.
- **Hooks:** [useConferences.ts](medconf-website/src/hooks/useConferences.ts), [useSaved.ts](medconf-website/src/hooks/useSaved.ts), [useAuth.ts](medconf-website/src/hooks/useAuth.ts).
- **Lib:** [supabase.ts](medconf-website/src/lib/supabase.ts), [types.ts](medconf-website/src/lib/types.ts).
- **Components:** `ConferenceCard`, `FilterPanel`, `SearchBar`, `PricingTable`, `CPDBadge`, `SaveButton`, `Navbar`, `Footer`.

### 2.3 Supabase
- Schema: [supabase_schema.sql](supabase_schema.sql) — run once in Supabase SQL editor.
- Tables: `conferences`, `pricing_tiers`, `scraper_sources`, `scraper_logs`, `user_profiles`, `saved_conferences`, `notification_preferences`.
- RLS: ON for all. Public read on `conferences` (where `archived = FALSE`) and `pricing_tiers`. User-data is owner-only via `auth.uid()`. Scraper tables admin-only (service key).
- Seeded sources: RCGP Events, BMJ Events, Royal Society of Medicine.

---

## 3. How to Run

### Frontend dev server
```bash
cd medconf-website
PORT=3001 npm run dev      # 3000 may be in use locally
# → http://localhost:3001
```

### Scraper (one-shot, for testing)
```bash
cd medconf-scraper
python main.py --run-now
```

### Scraper (start the weekly scheduler)
```bash
cd medconf-scraper
python main.py
```

### Required environment
- **Scraper** ([medconf-scraper/.env](medconf-scraper/.env)): `KIMI_API_KEY`, `KIMI_BASE_URL` (default `https://integrate.api.nvidia.com/v1`), `KIMI_MODEL` (default `moonshotai/kimi-k2.5`), `SUPABASE_URL`, `SUPABASE_KEY`, optional `SCRAPER_MAX_STEPS` (30), `SCRAPER_DELAY_SECONDS` (2), `SCRAPER_TIMEOUT_MS` (10000).
- **Website** ([medconf-website/.env.local](medconf-website/.env.local)): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

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

- **Money:** `price_gbp DECIMAL(10,2)`. UK only — no multi-currency yet.
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
