# Wave 2d batch review: "2d-C2 intl_multi" (ids 139-143)

Reviewer: independent, 2026-10-22. Harness re-run once per source (read-only), plus live curl checks and two small
throwaway probes in the scratchpad (not in the repo). No repo file other than this report was written or modified.

## Verdict table

| slug | class (confirmed) | verdict | shells (mine/builder) | registration advice |
|---|---|---|---|---|
| hematology | HematologyExtractor | PASS-with-notes | 8 / 8 | active |
| aan | AanExtractor | PASS-with-notes (code) | 4 / 4 | inactive, pending owner decision |
| aad | AadExtractor | PASS-with-notes (code) | 4 / 4 | inactive, pending owner decision |
| cns | CnsExtractor | PASS-with-notes (code) | 10 / 10 | inactive, pending owner decision |
| augis | AugisExtractor | PASS-with-notes | 4 / 4 | active |

Zero FAILs. `py_compile` clean for all five. `git status` shows only the five extractors and five JSONs as batch files;
no shared helper, `__init__.py`, workflow, `safe_fetch.py`, `pricing_tables.py` or `http_fetch.py` is modified. (The three
tracked modifications, `wave1d/mddus.json`, `wave2d/PLAN.md`, `reports/remediation/learned_patterns.json`, were already
dirty at session start and are not batch C2's.)

## Cross-cutting checks

**No LLM.** `grep "llm_call("` over the five files: zero call sites. `extract_detail(..., llm_call)` accepts the argument and
never uses it. A throwaway probe that passed a `llm_call` raising an exception ran CNS (annual 2027 + third-party row) and
ASH (APAC + MEMENA) end to end without tripping it. All five JSONs report `llm_calls: 0`.

**Imports and security.** Only `.base`, `.http_fetch`, `.tribe_events`, `.wordpress_generic` (family/shared) and top-level
`safe_fetch`. No import from another per-source module. No DB, no secrets, no raw httpx.
- External hops exist in exactly two files. AUGIS (Cvent summary) and CNS (third-party symposium organiser page).
- AUGIS (`augis.py`, Cvent hop): host taken from `urlparse().hostname`, compared by exact match or `.endswith(".cvent.com")`, then `check_url_safe` then `fetch_validated(deadline=30s, max_bytes=2 MB)`. No browser, no `fetch_html` on the external host. PASS.
- CNS (`cns.py`, organiser hop): `urlparse().hostname` exclusion list (cns.org, mcievents.com), `check_url_safe`, `fetch_validated(deadline=30s, max_bytes=2 MB)`, body decoded locally; no browser or `fetch_html`. The external page is only used if it names the edition year. PASS. CNS category listings use `self.browser.navigate` on hard-coded cns.org URLs only (society-own, allowed).
- hematology, aan and aad make no external hops at all.
- Note (low): CNS stores `organiser_url` (any non-cns, non-mci link whose text is "Visit website/Register") on every detail row without `check_url_safe`. Only http(s) links reach it (regex), and it is stored, not fetched, by this extractor; downstream remediator fetchers already go through safe_fetch. The external fetch itself is gated to slugs starting `new-calendarevent` (heuristic on the CMS auto-slug; it will skip a third-party event that gets a normal slug, and a future internal page with that prefix would trigger it).

**Politeness.** Full-run request estimate per site: ASH ~15, AAN 5, AAD ~7, CNS ~17, AUGIS ~7 (plus 1 external). All 1.0 s gaps,
sequential, retries only on failed fetch. My own totals per site (harness + curls + probe) stayed at or under about 22.

**Horizon (550 days, "18 months").** Consistent with other sources (crf 550, brit_thoracic 548, eadv 600, acep 730, escrs 800;
many emit everything upcoming). Rows I found beyond the horizon and not emitted, all real:
- AAN: Annual 2029 (Apr 14-18, Philadelphia), Fall Conference Oct 6-8 2028, APP Conference Oct 5 2028, Autoimmune Neurology Aug 4-5 2028 (Orlando). INFO-logged.
- AAD: Summer meeting July 13-16 2028 (New York). INFO-logged.
- CNS: Annual Meeting 2028 (Sept 16-20, Nashville) and 2029. Silent (no log line).
- hematology and augis: none beyond horizon.
Nothing is dropped in error, but the cut is arbitrary at series level: AAN Annual 2028 (548 days) is in while AAN Autoimmune Aug 2028 (653 days) is out, and
AAN Annual 2028 (548 days out) is the edge row; other AAN 2028 editions enter the feed one by one as the horizon rolls forward. Judgement: acceptable and consistent; the Commander may
prefer to lift to ~800 (escrs precedent) so all announced editions with a real date appear. CNS and the augis/hematology horizon skips should log at INFO like AAN/AAD for audit.

**Duplicated fee-grid parser.** `grid_tiers` is copied verbatim into hematology.py, aad.py and cns.py (hematology's is a superset:
`registration` suffix strip and "(Oct 1, 2026 - Jan 29, 2027)" window parsing; `section_for` parameter unused in all three). I verified 3 tiers per source live
(below) and the output is correct on all of them, including "Complimentary" rows (0.0) and CNS "Received between 6/1/2026- 9/30/26" windows. A shared grid parser
IS justified: three copies of ~90 lines, and the stated reasons (ASH deadline mislabelling, dropped "Complimentary", no CNS tables found by `pricing_tables`) are fixable once in
`pricing_tables.py`. Report only; do not do it before registration. Do it as a post-registration refactor with the three sources' harness output as the regression fixture.

**Fragments.** `#` fragments for uniqueness are already used by many sources (aaos, arrs, asgbi, bmfms, brit_thoracic, basl...), nothing in scraper/validator/database strips them; no new risk.

## 1. hematology (ASH, id 139) · PASS-with-notes · shells 8/8 · spot checks 2+ verified · advice: ACTIVE

Live checks (all match the extractor):
- Listing: Annual "December 12-15, 2026, New Orleans"; NA lines Jan 15-16 Chicago, Jan 22-23 New York, Jan 22-23 Seattle, Jan 29-30 Washington DC; APAC Feb 12-13 2027 Bangkok; MEMENA Mar 19-20 2027 Athens; LatAm Apr 2-3 2027 Santiago. Rows match.
- Four NA rows: distinct city+date each (Chicago 01-15, New York 01-22, Seattle 01-22, Washington, DC 01-29). Fragment is `#<city-slug>-<start-date>`, derived from the page's own text, so stable between runs; it only changes if ASH edits the date or city (then the old row would be archived and a new one created: acceptable). Seattle and New York share a date but have different fragments. PASS.
- Stale-text leak test, run live through `extract_detail`: MEMENA page still shows "Istanbul, Türkiye / February 13-14, 2026 / Hilton Istanbul Bomonti" next to the 2027 text. Extractor row: Athens, Greece, "Grand Hyatt Athens", 2027-03-19..20. No Istanbul text leaked. APAC page carries Kuala Lumpur 2026 text; row: Bangkok, "Centara Grand at CentralWorld", no Kuala Lumpur. PASS.
- Late-breaking abstract deadline: abstracts page says "The deadline for late-breaking abstract submission is October 28, 2026, at 11:59 p.m. Pacific time." Row has `abstract_deadline` 2026-10-28 with note. PASS.
- Fees (3 tiers each): Annual Active/International Member In-Person $900 (advance ends Oct 21 2026), Non-Member In-Person $1,700, Best Value $1,100: match the live grid. NA Non-Member $1,000 advance (ends Jan 4 2027) / $1,100 late: match. MEMENA ASH Member $450 advance (ends Mar 5 2027) / $500 late: match. APAC Non-Member $675/$825 (builder's check, plus my probe output 525/625 member, 675/825 non-member).
- Labels follow `Registration · <category> · <timeframe>`; `currency` "USD" on every tier.

Notes:
- Timing: the Annual Meeting advance window ended 2026-10-21 (23:59 PT) and late/on-site began 2026-10-22. The page still showed the advance grid at the time of my fetch; once ASH flips, the extractor will follow, and the expired advance tiers keep their deadline. Expected, as the builder says.
- NA rows have no venue (page lists only a hotel block); `with_venue 4/8` is correct.
- `abstract_deadline` accepted only when between today and start date: good guard.
- Dead parameter `section_for` in `grid_tiers`.
- No AI restriction found by the builder for hematology.org; I did not fetch its terms (not requested). 0 LLM calls anyway.

## 2. aan (id 140) · PASS-with-notes on code · shells 4/4 · spot checks 2 verified · advice: INACTIVE pending owner decision

Live listing `/events/upcoming-events` (server-rendered, matches the parser): Annual: Washington DC and online May 1-5 2027; Los Angeles and online Apr 22-26 2028; Philadelphia and online Apr 14-18 2029. Fall Conference: Las Vegas and online Oct 29-31 2027 / Oct 6-8 2028. APP: Las Vegas and online, ahead of the Fall Conference, Oct 28 2027 / Oct 5 2028. Autoimmune: Orlando and online Aug 4-5 2028. Extractor rows (Annual 2027, Annual 2028, Fall 2027, APP 2027) match dates and cities.

Terms and robots (the Commander needs this precisely):
- `https://www.aan.com/robots.txt`, generic block: `User-Agent: *` has `Allow: /` and `Disallow: /home-page/` only. So `/events/upcoming-events` and the series pages are NOT disallowed to a generic or browser User-Agent. The extractor's User-Agent is a Chrome string, so robots.txt does not technically block it.
- Same file, named agents with `Disallow: /` (and `Allow: /PressRoom`, `/PressRoom/`): grapeshot, Google-Extended, GPTBot, ChatGPT-User, CCBot, anthropic-ai, omgili, OAI-SearchBot, meta-externalagent, ClaudeBot, claude-web, PerplexityBot, Perplexity-User, Amazonbot, Applebot-Extended, Bytespider, DuckAssistBot, cohere-ai, AI2Bot, Diffbot, YouBot, MistralAI-User, GoogleAgent-Mariner (23 agents). Anthropic's own agents (ClaudeBot, anthropic-ai, claude-web) are on the list.
- Terms of Use (aan.com/terms-of-use, fetched): clause (e) says users agree "not to (i) use any robot, spider, scraper, or other automated means to access, monitor, index, or copy the Website or any content for any purpose without AAN's express prior written consent; (ii) engage in any text or data mining, web scraping, or similar data gathering or extraction". Clause (iii) (builder-quoted) forbids using content in AI/ML systems. This is the strongest restriction in the batch: the Terms prohibit the scraping itself, not just the AI use, regardless of robots.txt.
- Builder's JSON concerns state all of this (robots, Terms (e)(i)/(iii), status "partial", registration to be decided). PASS on disclosure.

Code notes:
- `aan.py` (cpd_accredited block, last lines of `extract_detail`): `cpd_accredited=True` is set from the series page text regardless of whether the page is this edition's (`same` gates only the description). Harness shows Annual 2028 and Fall 2027 rows as `cpd_accredited True` while their series pages describe a different (past or earlier) edition. Low risk but strictly an edition-leak; should be gated by `same`.
- 18-month cut drops 4 real editions (see Horizon). Annual 2028 (548 days) is the edge row.
- pricing empty is justified: Annual registration "opens early November"; Fall/APP pages describe the past 2026 edition; no sub-page, PDF or external link (cookie-banner link is a false positive).
- Shared-pipeline gap (builder flagged, I agree): merge step, abstract classifier and remediator can still send page text to the LLM; an owner-level exclusion is needed if AAN is ever activated. Out of this batch's scope.

## 3. aad (id 141) · PASS-with-notes on code · shells 4/4 · spot checks 3 verified · advice: INACTIVE pending owner decision

Live checks: Hands-On: Cosmetics page: "Oct. 24-25, 2026, Chicago IL / Palmer House Hilton", "Standard Registration Rate: $1,900", "Resident Standard Registration Rate: $760", AMA PRA Category 1 Credits, "Registration is open to AAD members only". Extractor row identical (2 tiers, cpd_points 10). `/registration/fees` grid: header "REGISTRATION CATEGORY | EARLY BIRD FEE | STANDARD FEE Beginning 2/17/27"; Physician member $1,135 / $1,365, Life member $355 / $465: matches (early-bird deadline stored 2027-02-17, derived from the page text; the header says standard begins 2/17, so the true last early day is 2/16, trivial). Dates page: 2027 San Francisco March 19-23, 2028 Washington DC March 17-21, July 22-25 2027 Chicago, July 13-16 2028 New York: matches.

Member-rate labelling: Hands-On tiers are `Registration · Standard Registration Rate (AAD members only)` and `Registration · Resident Standard Registration Rate (AAD members only)`. They are labelled as member rates, not presented as general prices. PASS. Wording "Standard Registration Rate" is the site's own; fine.

Terms and robots:
- `https://www.aad.org/robots.txt`: only `User-agent: *` with Disallow of /admin/, /commonlogin/, /marketieradmin/, /commerceadmin/, /analyzeradmin/, /webservice/, /product-type/, /view_cart/, /checkout/, /my_account/, /payment/, /order/, /marketiercampaign/ and five old `dw/monthly/...` archive paths. No AI-agent block. `/member/meetings/...` is not disallowed.
- `https://www.aad.org/terms-use` (fetched): copying/dissemination of Academy Content, "including the incorporation of Academy Content into any third-party database, compilation, or artificial intelligence learning model (through either manual or automated processes) without attribution to the Academy or for any commercial or non-educational purposes, is prohibited without prior written permission". Note the clause covers any third-party database or compilation, not only AI, and conditions it on attribution/commercial purpose. A directory that republishes AAD event descriptions arguably falls within it. Builder's concern ("forbids incorporating into any AI learning model") is accurate but understates the "third-party database" part. Recommend the owner brief include the database wording.
- Scraping per se is not prohibited in the text I read.

Code notes:
- Annual 2028 and summer 2027 rows come only from the dates page: dates and city, no fees/venue: honest.
- Annual 2027 `venue_name` empty: builder says not stated on microsite pages; not re-verified.
- Non-event cards, DermCatalyst (postponed) and `career-launch-on-demand` skipped: reasonable. `parse_event_cards` regex needs `class="card-title"` after `href`: layout-fragile, would silently yield zero cards on a markup change (the dates-page rows would still emit).
- Coverage: abstract-deadline gap is justified (Sept 2 2026 already past).

## 4. cns (id 142) · PASS-with-notes on code · shells 10/10 · spot checks 4 verified · advice: INACTIVE pending owner decision

Live checks:
- Annual 2026 fee grid `/annualmeeting/overview`: header "Early Bird Received on or before 5/31/2026 | Advanced Received between 6/1/2026- 9/30/26 | Regular Received After 9/30/26"; CNS Active (Domestic) Member $1,149 / $1,299 / $1,449; CNS Affiliate Member $450 / $550 / $650: extractor rows identical, deadlines 2026-05-31 and 2026-09-30. Annual dates page lists 2026 Oct 31-Nov 4 Washington DC, 2027 Oct 23-27 Phoenix, 2028 Sept 16-20 Nashville, 2029 Oct 6-10 San Diego.
- CNS Tumor Complications Course (browser-rendered page): "Grand Hyatt Deer Valley | Park City, Utah", "Jan 16, 2027 - Jan 18, 2027", Pricing $1,095 / $1,595 / $595 / $800 / $595 / $800: matches the 6 extracted tiers.
- Third-party symposium (`new-calendarevent-21`): I ran `extract_detail` live through the real hop. Organiser page `elpasochildrensfoundation.org` shows "REGISTRATION FEES: Surgeon $1,500.00, Orthotist $500.00, Pediatrician / Midlevel $300.00, Resident / Fellow $200.00, Registered Nurses / Students $150.00"; extractor returned exactly those 5 tiers, city El Paso. PASS (and the claimed `fetch_validated` hop works as described).
- Stale-tier leak, 2027 Annual Meeting row (live through `extract_detail`): dates 2027-10-23..27, Phoenix, `event_type`, `event_format`, `region` only; 0 tiers, no venue, no description. The 2026 fee grids did not leak. PASS.
- Priced rows 2 of 5 verified live (Annual 2026, Tumor Complications) plus the symposium. Rows with no pricing justified as the builder says (Oral Board virtual course, save-the-date placeholders).

Terms and robots:
- `https://www.cns.org/robots.txt`: `User-agent: *` Disallow `/Admin`, `/Ams`, `/MMS`; `User-agent: portal-crawler` empty Disallow (allow all). No AI-agent block; `/meetings`, `/meetings-detail`, `/annualmeeting` are not disallowed. Sitemaps listed for several CNS domains.
- `https://www.cns.org/cns-terms-service` (fetched): users may not "[reproduce/integrate] any content you accessed through this website, the CNS app, or any other CNS application or platform, into external applications, bots, software, or websites, including without limitation those using artificial intelligence ('AI') technologies and/or infrastructure, including deep learning, machine learning, generative AI, conversational AI, and large language models." The restriction covers integration into external applications and websites generally (AI is "including without limitation"), so a public directory site that reproduces CNS content is within the wording, not just LLM use. Builder's concern states only the AI part; the owner brief should include the "external applications ... or websites" wording.

Code notes:
- 93 tiers on the 2026 Annual Meeting (many member/non-member/trainee/exhibitor rows across multiple tables). Correct per page, but heavy; all three early/advanced/regular columns are past or about to be (event starts in 9 days).
- Annual-fee guard (`_annual_detail`) is hacky: header text is the first row of the first table via a `[:6000]` slice; works today, fragile on layout change. The primary `cur` check (first "YYYY CNS Annual Meeting" on the page) is the only guard against attaching the current microsite's venue and description to a later edition; works on the live page.
- Pagination: logs a WARNING if "N - M of T results" exceeds cards read; not followed. Max 5 per list today.
- Horizon skip for the annual editions and list items is silent (no INFO), unlike AAN/AAD.
- The Oral Board teaser (March 21-27) conflicts with the header (March 20-21): builder used header dates; consistent with brief.

## 5. augis (id 143) · PASS-with-notes · shells 4/4 · spot checks 4 verified · advice: ACTIVE

Live checks:
- `/Events` list table (plain HTML, no load-more control found, `load more` count 0): 20 Nov 2026 Yorkshire Regional Meeting at LNER Stadium (LNER Community Stadium), 27 Nov 2026 Palliative Care Symposium (Holiday Inn London), 17 Dec 2026 CholeSafe 2 (RCS England): matches the three listed rows (EventId 122, 118, 121).
- ASM 2027 banner on the home page, verbatim: "We are excited to announce the AUGIS ASM 2027 will take place on 15-17 September at ICC Wales!" (it sits under a stale "AUGIS ASM 2026" heading). The row's date 2027-09-15..17 comes straight from that sentence with the year stated in it; it is not a guess. Venue ICC Wales; city intentionally left empty; region Wales derived from the venue name. The `#asm-2027` source URL is stable.
- Cvent hop (CholeSafe 2): live Cvent summary shows "17 December 2026 / 08:00-18:00 / Royal College of Surgeons of England / 38-43 Lincoln's Inn Fields / London / WC2A 3PE"; extractor start_time 08:00, city London. Palliative Care Symposium: start 08:30, "Holiday Inn London - Gatwick Airport", city Horley (from Cvent per builder; not re-fetched by me).
- Fees behind login: booking pages say members must log in; `pricing_tiers: []` on all four. Correct and justified; builder checked booking page, info pages (CholeSafe flyer image) and the Cvent summary.

Robots/terms: `https://www.augis.org/robots.txt` is the stock DNN file (Disallow of admin/system paths such as /admin/, /bin/, /DesktopModules/, /images/, /Portals/, /Resources/...); nothing on `/Events`, `/Our-Events`, `/`. No AI block. Terms not re-fetched.

Notes:
- `event_type` is `conference` for all four, including CholeSafe 2 (a one-day surgical-safety training day, per Cvent page). I found no course or workshop wording on its info page, so `conference` is defensible but could be `course` if the owner wants.
- Yorkshire row has no city (only the stadium is published); region England inferred from "Yorkshire". The `_NATION` lookup is a small keyword map; a venue with an unlisted place gives no region, no fabrication.
- Horizon skip is silent (nothing to skip today).

## Items for the Commander

1. Register hematology and augis as active. Register aan, aad, cns as inactive until the owner decides. AAN is the hard case (Terms forbid automated access and text/data mining outright, and robots.txt blocks 23 AI agents including Anthropic's); AAD and CNS Terms restrict redistribution into third-party databases/websites and AI use, with scraping itself not prohibited in the text I read. The owner brief should quote the "third-party database" (AAD) and "external applications ... or websites" (CNS) wording, not only the AI wording.
2. If any of the three is activated, an LLM exclusion for the source in the shared merge/abstract/remediator steps is a prerequisite (shared files, out of this batch).
3. Optional fixes before registration (builder-owned, not blocking): gate `cpd_accredited` on `same` in `aan.py`; add INFO logs for horizon skips in cns/augis/hematology; consider horizon ~800 days so all announced editions appear.
4. Post-registration refactor: move the triplicated `grid_tiers` into `pricing_tables.py` (or a family module) using the three sources' harness output as regression fixture.
5. Hematology: the Annual Meeting advance window closed on 2026-10-21; the first live scrape after ASH flips its grid will exercise the late/on-site path. Worth a glance at the first daily run.
