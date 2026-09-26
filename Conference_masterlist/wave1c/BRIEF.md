# Wave 1b build brief (shared by all build agents)

You are building ONE per-source extractor for the MedConf scraper. Your prompt
gives you: `slug`, `source_id`, `ClassName`, and the recon record for your domain.

Repo root: `/Users/Sushil/Documents/Documents/IMT2/Side hustle/myTalk_conference app`
Scraper: `medconf-scraper/` · venv: `medconf-scraper/.venv/bin/python`

## Hard rules
- You may create/edit ONLY: `medconf-scraper/extractors/<slug>.py` and
  `Conference_masterlist/wave1c/<slug>.json`. Nothing else. Other agents are
  building sibling extractors in parallel — do NOT touch `extractors/__init__.py`,
  shared helpers, `browser.py`, `validator.py`, workflows, or any other file.
  If you believe a shared file needs a change, describe it in `concerns`.
- NO database access: never import `database`, never run `main.py`, never write
  to Supabase. NO git commit/push. Never print or log anything from `.env`.
- Be polite to the target site: ≤ ~60 requests total while developing, no
  parallel hammering.

## Read first (in this order, skim — don't dump whole files into context)
1. `medconf-scraper/extractors/PLAYBOOK.md` — the four-step onboarding protocol.
2. `medconf-scraper/extractors/base.py` — the `BaseExtractor` contract
   (`list_shells_override()`, `extract_detail(page, shell, llm_call)`).
3. ONE recent sibling as a template, whichever is closest to your site:
   - `extractors/rcpsych.py` — single listing page, httpx, fee table, mixed types
   - `extractors/rcsed.py` — paginated catalogue `?page=N`, several fee layouts
   - `extractors/rcpath.py` — single listing with upcoming/past split
   - `extractors/alsg.py` / `resus.py` — course + `sessions` (event_type='course')
4. Shared helpers you MUST reuse instead of re-implementing:
   - `extractors/http_fetch.py` → `fetch_html(url, browser=getattr(self, "browser", None))`
     for EVERY non-Playwright fetch. Never call `httpx` directly: several sites
     block GitHub-runner IPs (403 / 202 challenge) while working from a home IP,
     and `fetch_html` falls back to the real browser. In `extract_detail` the
     `page` is already on the event URL — prefer `page.content()` /
     `fetch_html(url, loaded_page=page)` over a second fetch.
   - `extractors/pricing_tables.py` — universal plain-number fee-table parser; try it first.
   - `extractors/specialty_classifier.py` — deterministic title→specialty backstop.
   - `extractors/abstract_classifier.py` — abstract open/deadline from page text.

## Requirements
- Hard fields are DETERMINISTIC (regex/DOM): title, start/end date (ISO
  YYYY-MM-DD), start_time, venue_name, city, region, event_format
  (`in_person`|`online`|`hybrid`), cpd_points, pricing_tiers, is_sold_out, booking_url.
- Soft fields (description, specialty) may use `llm_call(prompt)` — ONE call per
  event, small prompt (≤ ~3k chars of page text), asking for strict JSON. EVERY
  soft field needs a deterministic backstop for when the LLM returns None
  (specialty_classifier; description = first real paragraph / meta description,
  never nav text, cookie banners, CSS or legal disclaimers). (HQ LESSONS #4.)
- Never invent data. Unknown → None / []. No fee on the page → `[]` (a page that
  says "free" → one £0 tier). Currency other than GBP → set `currency` on each tier.
- Pricing labels: composite `[Section] · [Category] · [Timeframe]` joined with ` · ` (middot).
- `event_type`: `conference` | `course` | `workshop`. Multi-date courses: one parent
  with `sessions` like alsg.py/resus.py — not one row per date.
- Only upcoming events (today is 2026-09-21). Skip cancelled, past, and junk shells
  (archive pages, "no results", nav links). On-demand content: see how
  `extractors/rcem.py` uses `is_on_demand`; if unsure, skip and note it in `concerns`.
- If the generic DOM walker (`browser.get_event_cards_paginated`) already lists the
  site correctly, do NOT write a `list_shells_override` — return None and set the
  pagination fields in `source_row`. Override only when needed.
- Keep it one file, in the style of the siblings. No new dependencies.

## Test with the no-DB harness (from `medconf-scraper/`)
```
PYTHONPATH=. ./.venv/bin/python ../Conference_masterlist/wave1c/harness.py <slug> <ClassName> ../Conference_masterlist/wave1c/<slug>.json --details 5
PYTHONPATH=. ./.venv/bin/python ../Conference_masterlist/wave1c/harness.py <slug> <ClassName> ../Conference_masterlist/wave1c/<slug>.json --details 2 --force-fallback
```
(Write the JSON's `source_row` first — the harness reads it.) The second command
forces every `fetch_html` through Playwright — the path GitHub runners take when
blocked; shell count must match the normal run. Then open 3 of the tested event
pages yourself (curl/grep) and check dates, fees, venue against the harness
output — field by field. Fix and re-run until they match. Also run
`./.venv/bin/python -m py_compile extractors/<slug>.py`.

## Deliverable: `Conference_masterlist/wave1c/<slug>.json`
```json
{
  "source_id": 0, "slug": "", "class_name": "", "status": "done | partial | blocked",
  "file_written": "medconf-scraper/extractors/<slug>.py",
  "source_row": {
    "source_name": "", "society": "", "base_url": "",
    "default_event_type": "conference | course | mixed",
    "pagination_type": "single_page | page_query", "pagination_template": null,
    "max_pages_hint": 1, "detail_is_multipage": false, "active": true,
    "extraction_instructions": "2-5 sentences: listing structure, detail structure, gotchas"
  },
  "registry_comment": "one-line comment for EXTRACTOR_REGISTRY",
  "probe_results": {"shells": 0, "shells_forced_fallback": 0, "details_tested": 0,
                    "with_date": 0, "with_pricing": 0, "with_venue": 0, "with_description": 0, "with_specialty": 0},
  "test_urls": ["3 event URLs you verified by hand"],
  "spot_check": [{"url": "", "field": "", "site_says": "", "extractor_says": "", "match": true}],
  "concerns": ["anything unproven, flaky, blocked, or needing a shared-file change"]
}
```
`source_row` keys must be exactly those above (they map to `scraper_sources`
columns). Be honest in `status`/`concerns` — a wrong "done" costs more than a "partial".
Your final message: 5-10 lines — status, shell count, field coverage, concerns.

## Wave 1c addendum — JS / anti-bot sites
These sites need a real browser. Rules on top of the above:
- Use the Playwright `page`/`self.browser` FIRST for the listing (navigate, wait for the
  cards to appear with `page.wait_for_selector`, then read `page.content()` or query the DOM).
  `fetch_html()` with httpx is only for pages proven to be server-rendered.
- Cloudflare: if `page.goto` lands on a "Just a moment…" page, wait up to ~20 s polling
  `page.content()` for the challenge to clear (see `_poll_stable_body` in
  `extractors/http_fetch.py` for the pattern; reuse it via `fetch_html(url, reuse_page=True)`
  where possible). If the challenge NEVER clears in headless Chromium, do not fight it with
  stealth plugins or third-party bypass services — report `status: "blocked"` with exactly
  what you observed (status codes, challenge type, whether a longer wait helped). That is a
  valid, useful outcome.
- Budget the site politely: one browser, sequential navigation, ≤ ~60 page loads.
- `--force-fallback` in the harness is less meaningful here (you are browser-first); instead
  run the harness twice and confirm identical shell counts.
