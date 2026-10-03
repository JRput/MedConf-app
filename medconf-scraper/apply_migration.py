"""Apply a SQL migration file to the live Supabase Postgres in ONE transaction.

    ./.venv/bin/python apply_migration.py ../supabase/migrations/<file>.sql

Reads SUPABASE_DB_URL from .env.db (gitignored; the IPv4 session-pooler URL —
the direct db.<ref> host is IPv6-only). Rolls back on any error. Never prints
the connection string.
"""
import os
import sys
from urllib.parse import urlparse

import pg8000
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env.db"))
url = os.environ.get("SUPABASE_DB_URL")
if not url:
    sys.exit("SUPABASE_DB_URL missing from .env.db")
if len(sys.argv) < 2:
    sys.exit(__doc__)

u = urlparse(url)
sql = open(sys.argv[1]).read()
conn = pg8000.connect(
    user=u.username, password=u.password, host=u.hostname, port=u.port or 5432,
    database=u.path.lstrip("/") or "postgres", ssl_context=True, timeout=30,
)
conn.autocommit = False
cur = conn.cursor()
try:
    cur.execute(sql)
    conn.commit()
    print(f"APPLIED {os.path.basename(sys.argv[1])}")
except Exception as e:  # noqa: BLE001
    conn.rollback()
    sys.exit(f"FAILED (rolled back): {type(e).__name__}: {str(e)[:500]}")
for check in sys.argv[2:]:
    cur.execute(check)
    print(check[:60], "→", cur.fetchone())
conn.close()
