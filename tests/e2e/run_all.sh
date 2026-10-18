#!/usr/bin/env bash
# Run the whole suite from medconf-scraper (uses its venv). Needs the dev server on :3000 and the test accounts.
set -u
cd "$(dirname "$0")/../../medconf-scraper"
rc=0
for f in e2e_add_info e2e_submit e2e_moderation e2e_digest; do
  echo "=== $f ==="; ./.venv/bin/python "../tests/e2e/$f.py" || rc=1
done
exit $rc
