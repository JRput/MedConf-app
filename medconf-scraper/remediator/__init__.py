"""MedConf remediator — autonomous post-scrape data quality fixer.

Workflow:
  1. Detector identifies rows with missing/inaccurate fields
  2. Each fixer targets one field and re-extracts from the source page
  3. Validators sanity-check proposed values before write
  4. Patches land in Supabase; report written to reports/remediation/

The remediator NEVER touches extractor code. It enriches DATA. Code
improvements come from a separate Claude Code routine that reads
accumulated reports and proposes extractor patches.

CLI:
  python -m remediator --source N            # remediate one source
  python -m remediator --conference-id N     # remediate one row
  python -m remediator --all                 # all live sources
"""

__version__ = "0.1.0"
