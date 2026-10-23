# Mission: Safe-fetch mode for community rows (REMEDIATOR_SAFE_FETCH)

**Opened:** 2026-10-23 · **Owner approval:** "build it, activate hq and command centre" · **Commander:** this session

## Brief
Approved community submissions become ordinary `conferences` rows under source 1000. The remediator (our deep data-quality pass) must be allowed to run on them without ever fetching an attacker-chosen address, opening a browser on a hostile page, following links a hostile page supplies, parsing unbounded documents, or writing URL fields from fetched content. The flag defaults off, so the 141 scraped societies are untouched.

Security review 2026-10-23 (finder + Commander spot-checks): nothing exploitable runs today because the community job is `if: false` and `--all` skips inactive source 1000. The five things that WOULD be unsafe if it ran: blind redirects in the four shared fetchers and the image fetcher; the headless browser (ignores every Python address check); link-following from hostile HTML (external tier, registration sub-pages, nav pages); uncapped PDF/DOCX fetch + non-isolated parser; post-approval writes that publish without a moderator (incl. `organiser_url` / `booking_url` patches).

## What already exists (do not rebuild)
- `safe_fetch.py`: `check_url_safe`, `fetch_validated(url, url_check, max_hops, max_bytes, deadline)` (every hop address-checked, IP-pinned with SNI, streaming cap), `resolve_redirect_chain`, `html_to_text`, `enabled()` (reads `REMEDIATOR_SAFE_FETCH=1`), `fetch_text_html(url) -> (text, html)`, `SafeClient` (drop-in for `with httpx.Client(...) as c: c.get(url)`; raises `httpx.ConnectError` on refusal).
- `enrich_submissions.py` already uses all of it, and its `no_network()` shows the module-attribute patch pattern for tests.
- `remediator/runner.py` already writes a field only when the stored value is None (`value is None` guards at ~245/274/326); `pricing` replaces tiers wholesale only in that case.

## Task graph
```
T1 builder (sonnet, `sf-build`) ── wiring + policy + tests + workflow ──► T2 reviewer (sonnet, `sf-review`, fresh eyes, security brief)
                                                                             │ fixes back to T1 if needed
                                                                             ▼
T3 Commander: run full scraper test suite · apply nothing to DB · commit (explicit pathspecs) · push · `gh workflow run remediator-daily.yml`
   · verify `remediate-community` job green on runner with flag · verify the run's pytest step proves refusal of redirect-to-internal
T4 Commander: docs (CLAUDE.md §3 community step, this board CLOSED, memory), HQ LESSON if anything new
```

## T1 — builder scope (files it may touch)
`medconf-scraper/safe_fetch.py` (docstring + small helpers only), `remediator/fetcher.py`, `remediator/explorer.py`, `remediator/pdf_text.py`, `remediator/runner.py`, `extractors/http_fetch.py`, `extractors/abstract_classifier.py`, `vision.py`, `remediator/fixers/pricing.py` (only if a fetch bypasses the patched path), new `test_safe_mode.py`, `.github/workflows/remediator-daily.yml` (community job only). Nothing else. No git. No database writes. No running the remediator against the live DB.

### Requirements under `safe_fetch.enabled()`
1. **fetcher.py** `PageCache`: httpx path uses `SafeClient`; `_fetch_browser` returns None; Playwright allowlist/escalation skipped; tab-click paths skipped.
2. **explorer.py**: `fetch_page_text_and_html` uses `SafeClient`/`fetch_text_html`; `render_page` returns None (browser off); every followed URL (external-link tier, registration sub-pages, nav pages, promoted-pattern replays, `/fees`-style same-host guesses) passes `check_url_safe` and is fetched via the safe path, or the tier is disabled — document which. `_fetch_document_text`: `fetch_validated(..., max_bytes=PDF_MAX_BYTES)` (cap enforced while streaming), PDF only (skip DOCX), `pdf_to_text` run in a `subprocess` with a 20 s timeout and 20-page cap, never follow links found inside a document.
3. **http_fetch.py** `fetch_html`: `_fetch_httpx` via `SafeClient`; return None instead of any browser fallback.
4. **abstract_classifier.py** `_default_fetcher`: HTML via safe `fetch_html`; PDF branch via `fetch_validated` with a byte cap (no bare `httpx.get(follow_redirects=True)`).
5. **vision.py** `fetch_image_as_data_url`: under the flag return None (vision disabled for community rows in v1). Keep a one-line note on how to enable later (fetch_validated 2 MB + image content-type).
6. **runner.py write policy for source 1000 (any row whose `source_id == 1000`, regardless of flag):** never patch `organiser_url`, `booking_url`, `source_url` (the two `link_patches` / `_patch_row(... "organiser_url" ...)` sites); keep the existing "only when None" rule; values still go through existing validators (`sane_venue`, tier validation).
7. **Flag off:** byte-identical behaviour. Prove with a test that `enabled()` False leaves `httpx.Client` usage intact (e.g. the existing tests still pass unchanged).

### Tests — `test_safe_mode.py` (pytest, offline except one httpbin case)
- With `REMEDIATOR_SAFE_FETCH=1` (monkeypatch env): patch `httpx.Client` and `httpx.get` to raise `AssertionError("plain client used")` and `playwright.sync_api.sync_playwright` to raise; then call `PageCache.get_html`, `explorer.fetch_page_text_and_html`, `http_fetch.fetch_html`, `abstract_classifier._default_fetcher` (HTML and PDF branches), `_fetch_document_text`, `vision.fetch_image_as_data_url` against a URL served by a local `http.server` thread on 127.0.0.1 → each returns None/empty (loopback refused) and the plain-client assertion never fires.
- Redirect to internal: `SafeClient().get(<local server URL that 302s to http://169.254.169.254/>)` raises `httpx.ConnectError`. (Loopback is itself refused, so build the redirect test around `check_url_safe` + `resolve_redirect_chain` with a fake resolver, mirroring `test_safe_fetch.py`.)
- Size cap: a fake stream larger than `max_bytes` is cut off (reuse the pattern in `test_safe_fetch.py`).
- Write policy: with a fake supabase stub, a source-1000 row whose explorer result carries `external_url` produces NO `organiser_url`/`booking_url` patch; a source-5 row still does.
- Flag off: the module attributes are the original httpx callables.

### Workflow (`remediator-daily.yml`, community job only)
Remove `if: false`; add `REMEDIATOR_SAFE_FETCH: "1"` to the run step env; keep `continue-on-error: true` and `timeout-minutes: 30`; add a step before the run: `python -m pytest test_safe_mode.py test_safe_fetch.py -q` (fails the job, not the workflow); drop the Playwright install step for this job (browser is off); update the comment to say the mode is live and what it guarantees.

## T2 — reviewer brief (fresh eyes)
Read every diff hunk. For each of the five unsafe behaviours, name the line that now prevents it under the flag. Try to find a path that still reaches `httpx.Client(follow_redirects=True)`, `httpx.get`, or Playwright with the flag set (grep the whole scraper for call sites, including `fixers/*.py`, `audit.py`, `pdf_text.py`). Check the subprocess PDF parse cannot be bypassed and that DOCX is skipped. Check the write policy covers both URL-patch sites. Run the tests. Write `reports/security/safe_fetch_review_2026-10-23.md`. Severity + confidence per finding; "no findings" is a valid result.

## Model routing · cost · credentials
Sonnet for builder and reviewer; Commander verifies and gates. No paid services. No new credentials: the job already has `SUPABASE_URL`, `SUPABASE_KEY`, `KIMI_API_KEY`.

## Risk flags
- A hunk that changes behaviour with the flag OFF would affect all 141 sources → reviewer must check every hunk is inside an `enabled()` branch or is a pure refactor with identical behaviour.
- `subprocess` PDF parsing on GitHub runners: use `sys.executable -c`, pass bytes via stdin, timeout 20 s.
- The community job runs the LLM on fetched text and publishes to live rows; mitigated by the write policy (blank fields only, no URLs) and existing validators. Queue-for-review is a possible later hardening.

## Acceptance
All scraper tests green (`./.venv/bin/python -m pytest -q`), reviewer report with no open High/Medium, workflow dispatch shows `remediate-community` green with the flag and its pytest step passing on the runner, Commander spot-checks of three hunks.

## Status log
- 2026-10-23 — board written; T1 spawned.
- 2026-10-23 — T1 built: flag-gated safe paths in fetcher/explorer/http_fetch/abstract_classifier/vision, PDF subprocess parser (`pdf_to_text_isolated`), `_url_patches_allowed` write policy for source 1000, `test_safe_mode.py` (21 tests with test_safe_fetch), community job enabled with flag + test step. Whole suite (excluding live-API script test_api.py): 408 passed. Explorer tiers all kept and checked via the single safe fetch path; render_page/browser disabled; DOCX skipped. Not touched: remediator/audit.py browser probes (not reachable from `python -m remediator`).
- 2026-10-23 — Review fix pass: CFP PDFs parsed via subprocess (+%PDF check), test guard now records hits and asserts safe path used (fails on old code), SafeClient deadline (<=20 s), Accept-Encoding identity + encoding_refused, child env stripped, warnings logged. 25 safe-mode tests; suite green.
