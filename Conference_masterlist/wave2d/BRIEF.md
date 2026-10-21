# Wave 2d build brief (delta over wave 2c)

Read `Conference_masterlist/wave2c/BRIEF.md` IN FULL first — every rule there applies
(hard rules, read-first list, shared helpers, requirements, harness, deliverable JSON,
coverage checklist). This file only states what differs for wave 2d.

## Differences
- **Today is 2026-10-21.** Only upcoming events.
- **Deliverable path:** `Conference_masterlist/wave2d/<slug>.json` (same JSON shape as
  the 2c brief). Extractor stays at `medconf-scraper/extractors/<slug>.py`. You may
  create/edit ONLY those two files per source. Harness is unchanged:
  `PYTHONPATH=. ./.venv/bin/python ../Conference_masterlist/wave2c/harness.py <slug> <ClassName> ../Conference_masterlist/wave2d/<slug>.json --details 5`
  (and once more with `--force-fallback`; shell counts must match).
- **Your batch** is a key in `Conference_masterlist/wave2d/plan.json` → `batches`. Each
  entry gives `domain`, `source_id`, `slug` and the `recon` record (listing_url,
  pagination, event_type_mix, notes). `ClassName` = CamelCase(slug) + `Extractor`
  (e.g. `brit_thoracic` → `BritThoracicExtractor`). Use the given `source_id` in the JSON.
- **Platforms:** these are static HTML or non-WordPress CMS sites (Drupal, Umbraco, DNN,
  ColdFusion `index.cfm`, EventsAir, bespoke). Server-rendered → `fetch_html` first;
  templates `rcpsych.py` / `rcsed.py` / `rcpath.py`. Recon `js_required: true` → browser
  first per the wave 1c addendum. The recon `listing_url` is a starting point: confirm
  the real dated listing yourself (events, courses, meetings, calendar, education).
- **One-event congress sites (batch 2d-S):** subclass `extractors/single_congress.py`
  `SingleCongressExtractor` exactly like `croi.py` / `ukio.py` — constants only
  (HOME_URL, SOCIETY, EVENT_NAME, DEFAULT_SPECIALTY, DEFAULT_CURRENCY, optional
  REG_URLS / ABSTRACT_URLS / EDITION_URLS). Add a hook (`parse_place`, `edition_title`,
  `fees_from_pages`) only when the harness shows a concrete miss, and say which in
  `concerns`. Do NOT edit `single_congress.py`; describe family gaps in `concerns`.
- **Cloud access:** a GitHub-runner probe of your domains is running; the Commander will
  message you the result. Build meanwhile. If your domain comes back `blocked`, finish
  with `status: "blocked"` and what you observed; do not fight anti-bot measures.
- **Member-only fees / logins:** record only what the public page shows; never log in,
  never guess a members' rate. Say "members' fees behind login" in `concerns`.
- **Mixed societies** (`event_type_mix: mixed`): every row gets the right `event_type`
  (conference | course | workshop) — see the 3-way decision chain in `extractors/PLAYBOOK.md`.
- **UK societies:** GBP default; `region` is the UK nation or "international" per the
  siblings. International (EULAR, ESHRE, SIU, AAN, AAD, ASH, CNS, PCR): set `currency`
  per tier, city + country in `city`/`region`.

## Final message (5–10 lines per source)
status · shell count (normal / forced-fallback) · field coverage counts · 3 spot-checked
URLs · concerns (coverage checklist items verified, anything unproven, shared-file asks).
