-- Migration: directory query layer (Mission W2a)
--
-- Supports src/lib/directory-query.ts: replaces "download all 1,194+ rows
-- and filter in JS" (see ../reports/website-audit/code.md §2.1) with a
-- server-side view + facet RPC the directory can query with .range()/.in()/
-- .ilike() and get back one page, fast.
--
-- NOTE on applying this: supabase/migrations/ is frozen/stale per
-- CLAUDE.md §2.3 (does not reflect the live schema — course_sessions,
-- user_reminders, notifications, is_flagship, is_on_demand,
-- abstract_deadline_note, pricing_tiers.currency are all missing from it).
-- This file is additive only (new column, new view, new indexes, new
-- function) and does NOT touch existing columns/rows, so it is safe
-- to run directly against the live project (zcpszfbmvfylicpxgsfc) via the
-- Supabase SQL editor or `supabase db push` once the CLI is re-linked to
-- the correct project — see the W2a report for why this agent could not
-- apply it directly (no DB password / CLI link to the hotmail-org project
-- was available in this environment).

-- ============================================================
-- 1. Full-text search column
-- ============================================================
-- Generated + STORED so Postgres maintains it automatically on every
-- INSERT/UPDATE from the scraper — no app-side reindexing logic needed.
ALTER TABLE conferences
  ADD COLUMN IF NOT EXISTS search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('english',
      coalesce(conference_name, '') || ' ' ||
      coalesce(description, '') || ' ' ||
      coalesce(specialty, '') || ' ' ||
      coalesce(city, '')
    )
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_conferences_search_vector
  ON conferences USING GIN (search_vector);

-- ============================================================
-- 2. Supporting indexes for the filter/facet columns
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_conferences_start_date_live
  ON conferences(start_date) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_conferences_specialty_live
  ON conferences(specialty) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_conferences_region_live
  ON conferences(region) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_conferences_event_format_live
  ON conferences(event_format) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_conferences_source_id_live
  ON conferences(source_id) WHERE archived = FALSE;
CREATE INDEX IF NOT EXISTS idx_pricing_tiers_conference_price
  ON pricing_tiers(conference_id, price_gbp);

-- ============================================================
-- 3. directory_events view
-- ============================================================
-- One row per live conference with its min price/currency and society
-- pre-joined, so the directory list never needs an N+1 to pricing_tiers
-- or scraper_sources. `security_invoker = true` (PG15+) makes the view
-- enforce the QUERYING role's RLS on the underlying tables rather than
-- the view owner's — i.e. it stays exactly as RLS-safe as querying
-- conferences/pricing_tiers/scraper_sources directly (all three already
-- have public-read policies gated on archived = FALSE / TRUE, see
-- supabase_schema.sql's RLS section). No new policy is needed on the view
-- itself for that reason, but we grant SELECT explicitly below since a
-- view is a distinct relation.
--
-- `country_guess` is the same heuristic the data audit used (region/city
-- text matching, see ../reports/website-audit/data.md §1 "UK vs
-- international") — there is no structured country column on conferences,
-- so this is a best-effort bucket, not authoritative. Matches are case-
-- insensitive substring checks against UK nation/region names and the top
-- UK cities already observed in the data (code.md §1 city breakdown).
CREATE OR REPLACE VIEW directory_events
  WITH (security_invoker = true)
AS
SELECT
  c.id,
  c.conference_name,
  c.specialty,
  c.event_type,
  c.start_date,
  c.end_date,
  c.start_time,
  c.venue_name,
  c.city,
  c.region,
  c.event_format,
  c.is_sold_out,
  c.cpd_accredited,
  c.cpd_points,
  c.abstract_open,
  c.abstract_deadline,
  c.abstract_deadline_note,
  c.organiser_url,
  c.booking_url,
  c.source_url,
  c.description,
  c.is_on_demand,
  c.on_demand_original_date,
  c.is_flagship,
  c.created_at,
  c.updated_at,
  c.source_id,
  s.society,
  s.source_name AS source_short_name,
  p.price_from,
  p.price_currency,
  CASE
    WHEN c.event_format = 'online' THEN 'unknown'
    WHEN c.region ~* '(england|scotland|wales|northern ireland|^uk$)' THEN 'uk'
    WHEN c.city ~* '^(london|glasgow|edinburgh|liverpool|manchester|birmingham|cardiff|sheffield|belfast|leeds|bristol)$' THEN 'uk'
    WHEN c.region IS NULL AND c.city IS NULL THEN 'unknown'
    ELSE 'international'
  END AS country_guess,
  c.search_vector
FROM conferences c
LEFT JOIN scraper_sources s ON s.id = c.source_id
LEFT JOIN LATERAL (
  SELECT
    MIN(pt.price_gbp) AS price_from,
    (array_agg(pt.currency ORDER BY pt.price_gbp ASC))[1] AS price_currency
  FROM pricing_tiers pt
  WHERE pt.conference_id = c.id
) p ON true
WHERE c.archived = FALSE;

GRANT SELECT ON directory_events TO anon, authenticated;

-- ============================================================
-- 4. Facet RPC
-- ============================================================
-- Standard faceting: each facet's counts are computed with every OTHER
-- active filter applied, but NOT its own filter — so e.g. the format
-- counts tell you "how many rows would each format option leave you with
-- given your current type/specialty/region/etc selection", not just a
-- count of the page you're currently looking at.
--
-- p_specialty_raw takes RAW specialty values, already expanded from the
-- chosen parent slug(s) client-side via rawValuesForParent() in
-- src/lib/taxonomy/specialties.ts — the canonical taxonomy only exists in
-- TypeScript, so this function has no notion of "parent specialty" and
-- the specialty facet (returned as raw-value counts) is rolled up to
-- parents in directory-query.ts's queryFacets(), not here.
CREATE OR REPLACE FUNCTION directory_facets(
  p_q text DEFAULT NULL,
  p_date_from date DEFAULT NULL,
  p_date_to date DEFAULT NULL,
  p_format text[] DEFAULT NULL,
  p_type text[] DEFAULT NULL,
  p_specialty_raw text[] DEFAULT NULL,
  p_region text[] DEFAULT NULL,
  p_country text DEFAULT NULL,
  p_price text DEFAULT NULL,
  p_society text[] DEFAULT NULL,
  p_cpd boolean DEFAULT NULL,
  p_abstracts_open boolean DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
AS $$
  WITH base AS (
    -- Filters common to every facet: full-text search, date range,
    -- specialty and abstracts-open. (Format/type/region/country/price/
    -- society are applied per-facet below so each facet excludes itself.)
    SELECT *
    FROM directory_events d
    WHERE (p_q IS NULL OR p_q = '' OR d.search_vector @@ websearch_to_tsquery('english', p_q))
      AND (p_date_from IS NULL OR d.start_date >= p_date_from)
      AND (p_date_to IS NULL OR d.start_date <= p_date_to)
      AND (p_specialty_raw IS NULL OR d.specialty = ANY(p_specialty_raw))
      AND (p_abstracts_open IS NULL OR d.abstract_open = p_abstracts_open)
  ),
  by_format AS (
    SELECT coalesce(jsonb_object_agg(coalesce(event_format, 'unspecified'), cnt), '{}'::jsonb) AS j
    FROM (
      SELECT event_format, count(*) AS cnt FROM base
      WHERE (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
        AND (
          p_price IS NULL OR p_price = 'any'
          OR (p_price = 'free' AND price_from = 0)
          OR (p_price = 'under-100' AND price_from IS NOT NULL AND price_from < 100)
          OR (p_price = 'under-300' AND price_from IS NOT NULL AND price_from < 300)
        )
      GROUP BY event_format
    ) x
  ),
  by_type AS (
    SELECT coalesce(jsonb_object_agg(event_type, cnt), '{}'::jsonb) AS j
    FROM (
      SELECT event_type, count(*) AS cnt FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
        AND (
          p_price IS NULL OR p_price = 'any'
          OR (p_price = 'free' AND price_from = 0)
          OR (p_price = 'under-100' AND price_from IS NOT NULL AND price_from < 100)
          OR (p_price = 'under-300' AND price_from IS NOT NULL AND price_from < 300)
        )
      GROUP BY event_type
    ) x
  ),
  by_region AS (
    SELECT coalesce(jsonb_object_agg(coalesce(region, 'unspecified'), cnt), '{}'::jsonb) AS j
    FROM (
      SELECT region, count(*) AS cnt FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
      GROUP BY region
    ) x
  ),
  by_country AS (
    SELECT coalesce(jsonb_object_agg(country_guess, cnt), '{}'::jsonb) AS j
    FROM (
      SELECT country_guess, count(*) AS cnt FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
      GROUP BY country_guess
    ) x
  ),
  by_society AS (
    SELECT coalesce(jsonb_object_agg(coalesce(society, 'unspecified'), cnt), '{}'::jsonb) AS j
    FROM (
      SELECT society, count(*) AS cnt FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
      GROUP BY society
    ) x
  ),
  by_price_bucket AS (
    SELECT coalesce(jsonb_object_agg(bucket, cnt), '{}'::jsonb) AS j
    FROM (
      SELECT
        CASE
          WHEN price_from IS NULL THEN 'unknown'
          WHEN price_from = 0 THEN 'free'
          WHEN price_from < 100 THEN 'under-100'
          WHEN price_from < 300 THEN 'under-300'
          ELSE 'over-300'
        END AS bucket,
        count(*) AS cnt
      FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
      GROUP BY bucket
    ) x
  ),
  by_cpd AS (
    SELECT coalesce(jsonb_object_agg(cpd_accredited::text, cnt), '{}'::jsonb) AS j
    FROM (
      SELECT cpd_accredited, count(*) AS cnt FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (
          p_price IS NULL OR p_price = 'any'
          OR (p_price = 'free' AND price_from = 0)
          OR (p_price = 'under-100' AND price_from IS NOT NULL AND price_from < 100)
          OR (p_price = 'under-300' AND price_from IS NOT NULL AND price_from < 300)
        )
      GROUP BY cpd_accredited
    ) x
  ),
  -- Raw specialty counts (all filters except specialty itself applied).
  -- Rolled up to canonical parents in TypeScript — see queryFacets() in
  -- directory-query.ts.
  by_specialty_raw AS (
    SELECT coalesce(jsonb_object_agg(coalesce(specialty, 'unspecified'), cnt), '{}'::jsonb) AS j
    FROM (
      SELECT specialty, count(*) AS cnt FROM base
      WHERE (p_format IS NULL OR event_format = ANY(p_format))
        AND (p_type IS NULL OR event_type = ANY(p_type))
        AND (p_region IS NULL OR region = ANY(p_region))
        AND (p_country IS NULL OR country_guess = p_country)
        AND (p_society IS NULL OR society = ANY(p_society))
        AND (p_cpd IS NULL OR cpd_accredited = p_cpd)
        AND (
          p_price IS NULL OR p_price = 'any'
          OR (p_price = 'free' AND price_from = 0)
          OR (p_price = 'under-100' AND price_from IS NOT NULL AND price_from < 100)
          OR (p_price = 'under-300' AND price_from IS NOT NULL AND price_from < 300)
        )
      GROUP BY specialty
    ) x
  )
  SELECT jsonb_build_object(
    'format', (SELECT j FROM by_format),
    'type', (SELECT j FROM by_type),
    'region', (SELECT j FROM by_region),
    'country', (SELECT j FROM by_country),
    'society', (SELECT j FROM by_society),
    'priceBucket', (SELECT j FROM by_price_bucket),
    'cpd', (SELECT j FROM by_cpd),
    'specialtyRaw', (SELECT j FROM by_specialty_raw)
  );
$$;

GRANT EXECUTE ON FUNCTION directory_facets TO anon, authenticated;
