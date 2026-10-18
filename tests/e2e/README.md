# Community contributions E2E suite

Playwright + Supabase checks for add-info, /submit, moderation and the moderation digest.

## Needs
- Dev server on http://localhost:3000 (override with `E2E_BASE`).
- Two throwaway accounts (the moderator has `user_profiles.is_admin = true`): `test_submitter.json` and `test_moderator.json`, each `{email, password, user_id}`, in the folder named by `E2E_CREDS_DIR`. Never commit them.
- `medconf-scraper/.env` (service key) and `medconf-website/.env.local` (anon key); `medconf-scraper/.venv` with playwright, supabase, python-dotenv.

## Run (from the repo root)
```
tests/e2e/run_all.sh                                   # add_info, submit, moderation, digest
cd medconf-scraper && ./.venv/bin/python ../tests/e2e/e2e_screenshots.py   # 375x800 and 768x1024 into tests/e2e/screenshots/ (gitignored)
```
Each script prints PASS/FAIL per check and exits non-zero on failure. They are idempotent: each starts by deleting the submitter's contributions and leftover `https://example.org/e2e*` community events, and uses a timestamped organiser URL.

## Notes
- The digest flow is real, not a dry run: it replaces the unread 'moderation' notice for every admin.
- Service-role approvals pass `approve_unchecked: true`; the suite also asserts approval without it is refused while enrichment is 'waiting'.
