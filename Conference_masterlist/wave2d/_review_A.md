# Wave 2d batch "2d-A uk_static_hi" review (ids 116-122)

Reviewer: independent agent, 2026-10-21/22. Harness run once per source, curl/python spot checks, no product file edited, no commit.
All 7 extractors py_compile clean. Class names: BSSHExtractor, VascularSocietyExtractor, BAUSExtractor, HISExtractor, BBTSExtractor, AssociationOfBreastSurgeryExtractor, BASLExtractor.

## Gate summary

| slug | verdict | harness shells (mine/builder) | spot checks | registration advice |
|---|---|---|---|---|
| bssh (116) | PASS-with-notes | 7 / 7 | 2 verified | active |
| vascularsociety (117) | FAIL (one wrong price, one missing field) | 22 / 22 | 3 verified, 1 defect found | hold until fixed (small fix), then active |
| baus (118) | PASS-with-notes | 25 / 25 | 3 verified | active |
| his (119) | PASS-with-notes | 11 / 11 | 3 verified | active |
| bbts (120) | PASS-with-notes | 2 / 2 | 2 verified | active (low yield) |
| associationofbreastsurgery (121) | PASS | 10 / 10 | 2 verified | active |
| basl (122) | PASS-with-notes | 10 / 10 | 3 verified | active |

Repo hygiene: no shared helper, `__init__.py` or workflow is modified. `git status --short` shows tracked changes to `Conference_masterlist/wave1d/mddus.json`, `reports/remediation/learned_patterns.json` (both pre-existing) and `Conference_masterlist/wave2d/PLAN.md` (3 added lines about other batches, not this batch; Commander's own edit presumably). Nothing from this batch outside its 7 extractors and 7 JSONs.

Security convention (bssh, vascularsociety, baus, his, bbts, also aob and basl): PASS. Each file has an inline `ext_get()` that calls `safe_fetch.fetch_validated(url, deadline=+30s, max_bytes=2_000_000)`, no browser fallback; `host_is()` compares `urlparse().hostname` for equality or `.endswith("."+domain)`; no substring host tests (the one `frag in url` in his.py:744 is a path fragment, not a host test); only import of another module is the shared `safe_fetch`, `.base`, `.http_fetch`, `.pricing_tables`, `.abstract_classifier`. `fetch_html`/browser is used only on the society's own hosts (BASE_URL-joined). One mild point: his.py:908-913 and aob/vascular sub-page fetches use `urljoin(BASE_URL, href)`; an absolute off-site href in the side menu would go through `fetch_html`. Menu hrefs on these CMSs are same-site relative in all pages I saw, so low risk, but a `host_is(sub_url, own)` guard would close it.

## safe_fetch root-cause (requested)

Read `check_url_safe`, `pin_address`, `_pinned_request`, `fetch_validated`. Ran each URL at most twice (plus one unpinned httpx comparison).

| URL | check_url_safe | fetch_validated | reason | rejection correct? |
|---|---|---|---|---|
| https://www.technourologymeeting.com (from BAUS event 4752) | (True, "") A record 195.110.124.188 | rejected, "fetch failed: ConnectError" in 0.1 s | TLS: server presents certificate `CN=*.dadapro.com` (Register spa); SAN does not match `www.technourologymeeting.com`. Unpinned httpx and `curl` fail identically (`ssl_verify_result 20`, "no alternative certificate subject name matches target host name"). Apex host gives no response. | Yes. The organiser's TLS is misconfigured; refusing is right. Not a pinning/SNI bug (SNI is passed correctly via `sni_hostname`). |
| https://www.surgicalresearch.org.uk/ | (True, "") A 185.151.30.158 + AAAA 2a07:7800::158 | rejected "fetch failed: ConnectError" after 4.1 s, intermittently | `pin_address()` returns the FIRST allowed address from `getaddrinfo`, which here is the AAAA. This machine's IPv6 route is flaky: reproduced `[Errno 51] Network is unreachable` on the pinned IPv6, then 301 on the next two tries; `curl -4` gives 301, `curl -6` gave 000 once and 301 once. Unpinned httpx succeeded because the stdlib/anyio connect loop falls back to the A record. | NO, this is a bug in safe_fetch. Pinning to a single address removes the normal v6-then-v4 fallback. Any dual-stack host whose first-listed address is unreachable from the runner is wrongly refused. |
| https://www.fisconference.org/ | (True, "") A 185.151.30.203 + AAAA 2a07:7800::203 | ok both times (4.0 s, then 0.1 s), 71 KB, redirected to https://fisconference.org/ | Same dual-stack shape as surgicalresearch (same hosting range). The builder's "once rejected under load" is the same class: pinned first address (likely AAAA) transiently unreachable, or a 15 s read timeout; both surface as `rejected: fetch failed: <Exc>`. | Not a legitimate rejection; same bug (transient). |

Wider points in `fetch_validated`:
1. `pin_address` should return all allowed addresses and `fetch_validated` should try them in order (connect error on one -> next), still SNI/Host-pinned. Validation must keep rejecting if ANY resolved address is blocked (check_url_safe already does that), so trying the rest is safe.
2. Verdict `rejected` conflates SSRF refusals with plain transport/TLS errors (`except Exception -> "rejected"`). Return a separate verdict (e.g. `error`) so callers and logs can tell "blocked for safety" from "site down / cert broken". Today both look like a security block, which is what misled the builder.
3. The ext_get callers log the verdict only; adding the `final` string (it carries the exception class) to the warning would have shown ConnectError vs SSL immediately.
4. CI note: GitHub-hosted runners have no IPv6, and Python's `getaddrinfo` usually sorts unreachable v6 last, so the failure is less likely there, but it is not guaranteed; fix 1 removes the dependency.
No edit made to safe_fetch.py.

---

## bssh (116) - PASS-with-notes
- Harness: 7 shells (builder 7), 7/7 dated. Details: Scientific Meeting 2026 (19 tiers), Nerve and Tendon course (0 tiers, justified), Pulvertaft Wrist (1 tier from bookwhen hop).
- Spot checks verified live: (1) Scientific Meeting 4-6 Nov 2026, venue EICC Edinburgh, full-meeting £750 and one-day £415 for Fellows match the page; (2) Pulvertaft Wrist 19 Mar 2027, Derby Silk Mill, 1-day matches (the £180 is on the bookwhen hop, not re-fetched; consistent with builder's note).
- Fees empty for 3 events: pages say "More information will be available later"; builder checked side links. Justified.
- Notes: tier labels longer than 120 chars are cut mid-string with " … " (bssh.py:454, same helper in all 7 files), e.g. 'Standard Rate · BSSH Fellow members/AAHS Consultants / BSSH In … Consultant Associate members · Full Meeting (3 days)'. Readable but garbled; prefer shortening by category name or dropping the repeated "Standard Rate" section. Pre-congress workshops as extra tiers on parent row is acceptable.
- Specialty constant "Hand Surgery": accurate for BSSH but not in the website taxonomy (see below).
- JSON: source_row keys match 2c brief; instructions are actionable; status "done" honest.

## vascularsociety (117) - FAIL
- Harness: 22 shells (builder 22), 22/22 dated.
- Spot checks verified: (1) Ultrasound for Vascular Surgery course £310 early bird to 27 Sep, £395 standard matches; (2) Munich MAC hop fees (below) checked against https://mac-conference.com/registration/; (3) LINC Leipzig organiser_url.
- DEFECT 1 (wrong data): MAC Munich (events/193) gets 14 EUR tiers through the mac-conference.com hop, but "Registration fees · Industry representative" is stored as 1.5 EUR. The page prints "1.500,00 €" (German thousands format); the shared `parse_pricing_tables` reads it as 1.5. Real value is 1500. Also the day-ticket rows (€256/€92) and the full-congress rows (€462/€226) carry identical labels ("Registration fees · Physicians" x2, "Abstract Author" x2, ...), so the tiers cannot be told apart; workshop labels end with a trailing " |" and a date. The builder's concern text says Munich gives no tiers; that is stale, the hop works on this static WordPress site. Fix inside the extractor (shared parser may not be edited): after a hop parse, if any price < 5 EUR where the page text shows `\d\.\d{3},\d{2}`, repair or drop that tier; and drop or relabel duplicate-label rows (prefix "Day ticket Thu/Fri" from the preceding heading) or keep only the first block.
- DEFECT 2 (organiser_url): the ASM row (events/98, 25-27 Nov 2026, Liverpool) has NO organiser_url. `find_registration_link` is run only on the tab-content body; the "Registration and Programme" link (/annual-meeting/registration) is in the page nav, so it returns None, and `_follow_registration` returns tiers only. With the vision call empty (APITimeoutError on muse-glimmer-30b twice in my run, tiers = []), nothing points the remediator at reg-rates.png. Fix: have `_follow_registration` also return `reg_url` and set `result["organiser_url"] = reg_url` when no organiser link exists. booking_url (the event page) does link to the registration page in its nav, so the remediator could still find it, but do not rely on that.
- LINC Leipzig (events/205): organiser_url IS stored (https://app.leipzig-interventional.com/.../linc2027/registration), tiers empty by design (JS app). OK.
- ASM fee image is empty by design and the concern is documented; status "partial" is honest, but the Munich statement above is not.
- Specialty constant "Vascular Surgery" is right and mapped in the website; the LLM sometimes returns "Vascular Medicine" (Munich), which is unmapped.

## baus (118) - PASS-with-notes
- Harness: 25 shells (builder 25), 25/25 dated. /events/date/2027 and 2028 year routes still return 502 in my run, so the sitemap path is live.
- Sitemap verified: https://www.baus.org.uk/sitemap.xml returns 200 (153 KB) with 99 /professionals/events/<id>/ URLs. The 8 sitemap-derived rows take dates from each detail page's add-to-calendar JSON (`_read_header`, baus.py:~790), not invented: checked 15th TechnoUrology (events/4752): `"startDate":"2027-01-28","endDate":"2027-01-29"`, location "Turin, Italy" matches. Cap of 60 candidates and `floor = min(seen)-500` keep fetches bounded; total requests in my run stayed within 25 fetch calls to the site plus own-host details (harness itself reads ~10 pages; the extractor's sitemap loop is the heavy part, builder says up to ~45 cached fetches: slightly over the 25-per-site politeness guide during the listing phase, acceptable but flag it).
- Spot checks verified: (1) BAUS Section of Oncology annual meeting 19-20 Nov 2026, Edgbaston Stadium, Day 1 Urology Trainee £144 matches; (2) Technourology sitemap row above; (3) Karl Storz course.
- Fees on Eventbrite/Arlo/Wix/FEDRA hosts are not parsed: ESSIC 2026 shows 0 tiers rather than wrong tiers. Correct behaviour.
- Note: Karl Storz Endoscopic Skills Course has two rows both labelled "Registration Fee · Non-member" (£175 and £225). The BAUS page really prints it that way ("Coming soon" ticket table), so it is faithful, but a user cannot tell the two apart; acceptable, mention in notes only.
- Fragility: stays dependent on sitemap.xml until the Cloudflare 502 clears. Cloud runners may be challenged; Commander should do one real runner trial (builder already asks this).
- Ellipsis label truncation applies (baus.py:461).

## his (119) - PASS-with-notes
- Harness: 11 shells (builder 11), 11/11 dated. Details: Insight Webinar (0 tiers, Teams registration), IPC Training Day (3 tiers £25/£100/£200), IPC leaders' course (4 tiers).
- FIS 2026 fees verified live through both hops: ran `_two_hop_fees` on the live /fis-his/fis-2026/ body: organiser https://fitwise.eventsair.com/fis-2026, 9 GBP tiers (not 3): society member full £724 / two days £600 / one day £300, non-member full £858 / £722 / £361, participating-society professionals £536 / £416 / £208. Builder's £724/£858 match the live registration-and-fees page. Hop 1 correctly skips the typekit CSS link that appears first on the raw page (body-scoped), and the eventsair host test uses `host_is`.
- HISCON 2027: header literally reads "08 June 2027 - 09 June 2026" and the body says "returns to London on 8-9 June 2027". Repair logic (his.py:~850) is generic: if end < start, re-run `parse_date_range(body[:900], year_of_start)` and accept only when its start equals the header start. Not hard-coded. Result 2027-06-08..09 correct.
- Spot checks verified: FIS fees, HISCON dates, plus IPC leaders' course exists with early-bird/standard tiers (early_bird_deadline None: the page gives no deadline date, checked).
- Notes: the early-bird tiers in the IPC leaders' course carry `is_early_bird` True without a deadline; fine. Ellipsis labels (his.py:473) show in the FIS rows ("FIS participating society healthcare profession … ntists - Full conference"): the clipped words are meaningful here; shorten to the final category instead. "(from 28 Sep)" is baked into every FIS label; harmless but stale after the date.

## bbts (120) - PASS-with-notes
- Harness: 2 shells (builder 2), both dated. Only /events/bbts_events/ hrefs become events; I listed the live feed: 5 event pages (isbt, lmce-2026, rcpath-shot, scotblood-2026, two werfen webinars) plus ?month archives. No news/blog/council item is emitted. ISBT page has no date (skipped, correct), Scotblood is 28-29 May 2026 (past), Werfen webinars past.
- Spot checks verified: LMCE "Dates: October 21 (Wed) - 23 (Fri), 2026, Grand Walkerhill, Seoul" matches 2026-10-21..23; RCPath & SHOT "Virtual two half day event on 25 th and 26 th Nov 2026" matches 2026-11-25..26, online.
- Notes: LMCE is a Korean society congress that started on the review date, so it is effectively past on arrival; the description of the RCPath event keeps the page's "25 th and 26 th" spacing artefact. UNPROVEN branch: the annual-conference regex has only run on a past edition (builder states this). Zero tiers justified (RCPath REGISTER HERE page followed, no fees). Advice: register active; expect 0-2 rows until BBTS 2027 is announced.

## associationofbreastsurgery (121) - PASS
- Harness: 10 shells (builder 10), 10/10 dated; card date is the LAST day so detail pages are read during listing; verified.
- Spot checks verified: (1) ABS-OOPS course live "25 January 2027 - 26 January 2027, Saïd Business School, Oxford, 2 days" matches 2027-01-25..26; (2) OOPS /registration/ page: "Early rate - Consultants & SAS Doctors registration Members £900, Early rate - Trainees £600, Early Rate - Overseas £1100, Nurses £200" matches the 4 tiers.
- Advanced Skills second date: builder's reasoning is slightly off but the outcome is right. On the live calendar the sequence is "... Advanced Skills in Breast Disease Management 19 - 21 April 2027 Selwyn College, Cambridge, Read More, 2 Days | ABS Conference 2027 10 - 11 May 2027 ICC Wales ...". The "2 Days / 11 May" belongs to the ABS Conference 2027 card (last day 11 May), not to a second Advanced Skills session. No second session exists; not emitting one is correct.
- Notes: `extract_abstract_info` false-negative worked around inline (open=True when future deadline plus "now open"); reasonable and the shared bug is correctly reported. Tier label "Delegate fees · Member · Members" is redundant. Free event gets a 0.0 tier. Good.

## basl (122) - PASS-with-notes
- Harness: 10 shells (builder 10), 10/10 dated; `--details 10` shows every row. booking_url is listing URL + `#eventContentNNN`, stable CMS id.
- Spot checks verified: (1) Rare Liver Diseases Masterclass 20-21 Nov 2026, Hallam Conference Centre London: 6 tiers match the page (members £110/£95, trainees £80/£75, non-members £150/£135); (2) Introduction to Hepatology 6 Nov: "FREE to attend for BASL & BSG Trainee Members (a deposit of £40 ... refunded), non-member £75" matches the 3 tiers (deposit, £0, £75); (3) Basic Science Retreat £350 present on the page.
- Fragment check: none of the tier labels is a sentence fragment; all are short category phrases.
- Notes: Introduction to Hepatology page says "Registration now closed" but the row has no sold-out flag (is_sold_out None); start_time 09:30 is the registration slot, not the programme start (builder noted). Events that merely sit in a mixed "All Events" list (BSG HPB Trainee Symposium, BLTG webinars) are kept: acceptable, they are CPD-relevant to hepatology but not BASL-run; say so in registry comment. LLM overrode the constant to "Gastroenterology" for BSG/BLTG rows, which is a mapped value, fine.

---

## Specialty constants vs website taxonomy
`medconf-website/src/lib/taxonomy/specialties.ts` (`RAW_TO_CANONICAL`) is the only raw to parent map; unknown raws fall to "Other". Constants used and mapping:

| society | constant | in taxonomy? | note |
|---|---|---|---|
| BSSH | Hand Surgery | no -> Other | correct clinically; suggest map to msk-trauma-orthopaedics (existing 'Orthopaedics' value) or add key |
| Vascular Society | Vascular Surgery | yes -> surgery-general | fine |
| BAUS | Urology | yes (own parent) | fine |
| HIS | Infection Prevention and Control | yes -> infectious-disease-immunology | fine |
| BBTS | Transfusion Medicine | no -> Other | map to haematology |
| ABS | Breast Surgery | no -> Other | map to surgery-general (or oncology) |
| BASL | Hepatology | no -> Other (only 'Gastroenterology & Hepatology' is mapped) | map to gastroenterology |
Other raw values the LLM produced: "Vascular Medicine" (unmapped), "Laboratory Medicine" (mapped to pathology), "Gastroenterology" (mapped). The constants are the right choice for single-specialty societies (they are accurate and consistent per society), but 4 of 7 will show as "Other" in the website parent filter until entries are added. This is a one-file website change the owner must approve (specialties.ts); not a scraper issue.

## Cross-cutting issues
1. safe_fetch pins only the first resolved address (see root-cause above); this will intermittently drop legitimate dual-stack organiser sites, in CI as well as locally. Affects every extractor that hardened to `fetch_validated`.
2. `parse_pricing_tables` (shared) mis-reads European thousands format ("1.500,00 €" -> 1.5) and merges same-labelled blocks. Already noted by the builder for other columns; the 1.5 EUR is a new, concrete wrong-price case (vascularsociety Munich MAC).
3. Mid-label " … " truncation helper copied into all 7 files; produces garbled labels for long category names (bssh, his).
4. Hardening note in the vascularsociety JSON is true for hops, but its concern text about Munich/Zurich/Find-Your-Algorithm giving no tiers does not match the harness (Munich returns tiers).
5. Politeness: baus sitemap fallback can fetch up to ~45 own-host detail pages in the listing phase (cached afterwards); other six sources stay well under 25.

## Decisions for the Commander
- vascularsociety: send back for two small fixes (Munich 1.5 EUR / duplicate labels; ASM organiser_url). Everything else in the batch can be registered active now.
- Approve or defer a safe_fetch fix (try every validated address; separate `error` verdict). Until then expect sporadic empty hops on dual-stack sites; none of the 7 extractors depends on a hop for its core fields.
- Decide on website taxonomy additions (Hand Surgery, Breast Surgery, Hepatology, Transfusion Medicine, Vascular Medicine) so these societies do not land in "Other".
- baus: run one real GitHub-runner trial for sitemap.xml and event pages (Cloudflare) before trusting 2027 coverage.
