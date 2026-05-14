# Data Flow - Where Extracted Data Goes

## Summary

The agentic scraper extracts conference data and uploads it to **Supabase** (a PostgreSQL database).

## Database Location

- **Supabase URL**: `https://ystpjjhfgfraxcnvbish.supabase.co`
- **Database Type**: PostgreSQL (via Supabase)

## Data Flow Process

1. **Extraction** (`llm_agent.py`)
   - Browser navigates to source website
   - LLM (Kimi K2.5) extracts conference data from page content
   - Returns raw conference data as JSON

2. **Validation** (`validator.py`)
   - Validates required fields: `conference_name`, `source_url`
   - Validates date formats (YYYY-MM-DD)
   - Validates pricing tiers
   - Returns cleaned data or validation errors

3. **Database Storage** (`database.py` → Supabase)
   - **Table: `conferences`** - Main conference data
     - Fields: conference_name, specialty, start_date, end_date, venue_name, city, region, cpd_accredited, cpd_points, abstract_open, abstract_deadline, organiser_url, source_url, description
   - **Table: `pricing_tiers`** - Pricing information
     - Fields: conference_id, tier_label, price_gbp, is_early_bird, early_bird_deadline
   - **Table: `scraper_logs`** - Run history
     - Fields: source_id, run_started_at, run_ended_at, status, conferences_found, conferences_inserted, conferences_updated, errors_encountered, error_details

4. **Duplicate Detection**
   - Uses `source_url` as unique identifier
   - If conference exists: **updates** existing record
   - If new: **inserts** new record

## Current Database Status

Based on latest check:
- ✅ **3 scraper sources** configured (RCGP Events, BMJ Events, Royal Society of Medicine)
- ❌ **0 conferences** in database (previous runs failed)
- ⚠️ **5 scraper log entries** showing "failed" status
- Latest error: `'NoneType' object has no attribute 'strip'` (likely in LLM response parsing)

## Why Test Data Wasn't Saved

The `test_scraper_simple.py` test:
- ✅ Successfully extracts data using LLM
- ❌ **Does NOT save to database** (only tests extraction, not full pipeline)

To actually save data, you need to run:
- `python3 test_scraper.py --hardcoded` (full pipeline with hardcoded source)
- `python3 test_scraper.py` (full pipeline using database sources)
- `python3 main.py --run-now` (full scheduled run)

## Database Tables Structure

### `conferences` table
```sql
- id (SERIAL PRIMARY KEY)
- conference_name (TEXT NOT NULL)
- specialty (TEXT)
- start_date (DATE)
- end_date (DATE)
- venue_name (TEXT)
- city (TEXT)
- region (TEXT)
- cpd_accredited (BOOLEAN)
- cpd_points (INTEGER)
- abstract_open (BOOLEAN)
- abstract_deadline (DATE)
- organiser_url (TEXT)
- source_url (TEXT UNIQUE NOT NULL)
- description (TEXT)
- archived (BOOLEAN)
- created_at (TIMESTAMPTZ)
- updated_at (TIMESTAMPTZ)
```

### `pricing_tiers` table
```sql
- id (SERIAL PRIMARY KEY)
- conference_id (INTEGER REFERENCES conferences)
- tier_label (TEXT NOT NULL)
- price_gbp (NUMERIC)
- is_early_bird (BOOLEAN)
- early_bird_deadline (DATE)
```

### `scraper_logs` table
```sql
- id (SERIAL PRIMARY KEY)
- source_id (INTEGER REFERENCES scraper_sources)
- run_started_at (TIMESTAMPTZ)
- run_ended_at (TIMESTAMPTZ)
- status (TEXT)
- conferences_found (INTEGER)
- conferences_inserted (INTEGER)
- conferences_updated (INTEGER)
- errors_encountered (INTEGER)
- error_details (TEXT)
```

## Accessing the Data

You can access the data via:
1. **Supabase Dashboard**: https://supabase.com/dashboard
2. **Supabase API**: REST API endpoints
3. **Python client**: Using `supabase` library (as in `database.py`)
4. **SQL queries**: Direct PostgreSQL access via Supabase


