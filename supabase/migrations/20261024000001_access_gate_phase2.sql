-- ============================================================
-- Access gate, Phase 2 (2026-10-24): anonymous visitors can no longer read
-- directory data. The public teaser is served only through three narrow
-- SECURITY DEFINER functions. Board: MISSION_BOARD_ACCESS_GATE.md.
--
-- APPLY PLAN (in this order):
--   1. Deploy the website Phase 1+2 code (the code that calls home_preview(),
--      event_preview() and sitemap_events() and uses cookie-aware clients).
--   2. cd medconf-scraper &&
--      ./.venv/bin/python apply_migration.py \
--        ../supabase/migrations/20261024000001_access_gate_phase2.sql <checks...>
--      (checks = the lines of 20261024000001_checks.txt)
--   3. Smoke: anonymous /, /conferences/<id>, /sitemap.xml;
--      signed-in /conferences (list, filters, facets).
--   4. On any failure run 20261024000001_rollback.sql via the same tool.
--
-- DEPLOY ORDER WARNING: apply ONLY after the website code that calls
-- home_preview / event_preview / sitemap_events is deployed. Production reads
-- anon data until then; applying earlier breaks every anonymous page.
--
-- What changes:
--   * SELECT policies on conferences, pricing_tiers, course_sessions,
--     scraper_sources, community_facts, community_tiers become TO authenticated
--     (same predicates). Write policies and service_role are untouched
--     (service_role bypasses RLS).
--   * anon loses SELECT on directory_events and EXECUTE on directory_facets.
--     Postgres grants EXECUTE on new functions to PUBLIC by default, so the
--     revoke names PUBLIC too; otherwise anon would keep access through it.
--   * New functions (SECURITY DEFINER, search_path = public, read-only, no
--     auth.uid()/current_user logic): home_preview(), event_preview(integer),
--     sitemap_events(). They read the BASE tables, not the security_invoker
--     view, so they do not depend on view grants or invoker semantics.
--
-- Idempotent: DROP POLICY IF EXISTS / CREATE OR REPLACE / REVOKE / GRANT.
-- ============================================================

-- ------------------------------------------------------------
-- 1. Read policies: authenticated only
-- ------------------------------------------------------------
DROP POLICY IF EXISTS "Anyone can view conferences" ON public.conferences;
DROP POLICY IF EXISTS "Authenticated can view conferences" ON public.conferences;
CREATE POLICY "Authenticated can view conferences"
    ON public.conferences FOR SELECT TO authenticated
    USING (archived = FALSE);

DROP POLICY IF EXISTS "Anyone can view pricing tiers" ON public.pricing_tiers;
DROP POLICY IF EXISTS "Authenticated can view pricing tiers" ON public.pricing_tiers;
CREATE POLICY "Authenticated can view pricing tiers"
    ON public.pricing_tiers FOR SELECT TO authenticated
    USING (TRUE);

DROP POLICY IF EXISTS "Anyone can view course sessions" ON public.course_sessions;
DROP POLICY IF EXISTS "Authenticated can view course sessions" ON public.course_sessions;
CREATE POLICY "Authenticated can view course sessions"
    ON public.course_sessions FOR SELECT TO authenticated
    USING (TRUE);

DROP POLICY IF EXISTS "Anyone can view scraper sources" ON public.scraper_sources;
DROP POLICY IF EXISTS "Authenticated can view scraper sources" ON public.scraper_sources;
CREATE POLICY "Authenticated can view scraper sources"
    ON public.scraper_sources FOR SELECT TO authenticated
    USING (TRUE);

-- Community facts / tiers (20261018000000_community_contributions.sql)
DROP POLICY IF EXISTS "Published facts are public" ON public.community_facts;
DROP POLICY IF EXISTS "Published facts are visible to authenticated" ON public.community_facts;
CREATE POLICY "Published facts are visible to authenticated"
    ON public.community_facts FOR SELECT TO authenticated
    USING (is_published OR public.is_admin());

DROP POLICY IF EXISTS "Published tiers are public" ON public.community_tiers;
DROP POLICY IF EXISTS "Published tiers are visible to authenticated" ON public.community_tiers;
CREATE POLICY "Published tiers are visible to authenticated"
    ON public.community_tiers FOR SELECT TO authenticated
    USING (is_published OR public.is_admin());

REVOKE SELECT ON public.community_facts, public.community_tiers FROM anon;

-- ------------------------------------------------------------
-- 2. Directory view and facets RPC: authenticated only
-- ------------------------------------------------------------
REVOKE SELECT ON public.directory_events FROM anon;

REVOKE EXECUTE ON FUNCTION public.directory_facets(
  text, date, date, text[], text[], text[], text[], text, text, text[], boolean, boolean
) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.directory_facets(
  text, date, date, text[], text[], text[], text[], text, text, text[], boolean, boolean
) TO authenticated, service_role;

-- ------------------------------------------------------------
-- 3. home_preview(): anonymous homepage teaser (counts + names only)
-- ------------------------------------------------------------
-- "Live" mirrors the homepage total: upcoming (start >= today or undated)
-- plus ongoing (started, end >= today). Current date is the database's (UTC).
-- this_month mirrors resolveDatePreset('this-month') + the overlap rule in
-- directory-query.ts: start <= month end AND (end >= today OR (end IS NULL
-- AND start >= today)). closing_soon list: next deadlines inside 14 days; if
-- none are inside the window, the next 5 upcoming deadlines (homepage
-- fallback), so the count can be 0 while the list is not empty.
-- Output deliberately excludes fees, CPD, venue, URLs, exact deadlines and
-- descriptions. days_left is relative only.
CREATE OR REPLACE FUNCTION public.home_preview()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH live AS (
    SELECT c.id, c.conference_name, c.specialty, c.event_format, c.start_date,
           c.end_date, c.abstract_open, c.abstract_deadline, s.society
    FROM public.conferences c
    LEFT JOIN public.scraper_sources s ON s.id = c.source_id
    WHERE c.archived = FALSE
      AND (c.start_date IS NULL
           OR c.start_date >= current_date
           OR c.end_date >= current_date)
  ),
  month_rows AS (
    SELECT * FROM live
    WHERE start_date IS NOT NULL
      AND start_date <= (date_trunc('month', current_date) + interval '1 month' - interval '1 day')::date
      AND (end_date >= current_date OR (end_date IS NULL AND start_date >= current_date))
  ),
  closing AS (
    SELECT * FROM live
    WHERE abstract_open IS TRUE
      AND abstract_deadline >= current_date
  ),
  closing_window AS (
    SELECT * FROM closing WHERE abstract_deadline <= current_date + 14
  ),
  closing_list AS (
    SELECT id, conference_name, society, abstract_deadline
    FROM (
      SELECT * FROM closing_window
      UNION ALL
      SELECT * FROM closing WHERE NOT EXISTS (SELECT 1 FROM closing_window)
    ) u
    ORDER BY abstract_deadline ASC, id ASC
    LIMIT 5
  ),
  spec AS (
    SELECT specialty, count(*) AS n FROM live
    WHERE specialty IS NOT NULL AND specialty <> ''
    GROUP BY specialty ORDER BY n DESC, specialty ASC LIMIT 40
  ),
  soc AS (
    SELECT society, count(*) AS n FROM live
    WHERE society IS NOT NULL AND society <> ''
    GROUP BY society ORDER BY n DESC, society ASC LIMIT 40
  )
  SELECT jsonb_build_object(
    'counts', jsonb_build_object(
      'events', (SELECT count(*) FROM live),
      'societies', (SELECT count(DISTINCT society) FROM live WHERE society IS NOT NULL AND society <> ''),
      'specialties', (SELECT count(DISTINCT specialty) FROM live WHERE specialty IS NOT NULL AND specialty <> ''),
      'closing_soon', (SELECT count(*) FROM closing_window),
      'this_month', (SELECT count(*) FROM month_rows),
      'online_this_month', (SELECT count(*) FROM month_rows WHERE event_format = 'online')
    ),
    'closing_soon', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
               'id', id, 'name', conference_name, 'society', society,
               'days_left', (abstract_deadline - current_date))
             ORDER BY abstract_deadline ASC, id ASC)
      FROM closing_list), '[]'::jsonb),
    'this_month', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
               'id', id, 'name', conference_name, 'society', society,
               'start_date', start_date, 'end_date', end_date)
             ORDER BY start_date ASC, id ASC)
      FROM (SELECT * FROM month_rows ORDER BY start_date ASC, id ASC LIMIT 12) m), '[]'::jsonb),
    'specialties', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('specialty', specialty, 'count', n) ORDER BY n DESC, specialty ASC)
      FROM spec), '[]'::jsonb),
    'societies', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('society', society, 'count', n) ORDER BY n DESC, society ASC)
      FROM soc), '[]'::jsonb)
  );
$$;

REVOKE ALL ON FUNCTION public.home_preview() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.home_preview() TO anon, authenticated;

-- ------------------------------------------------------------
-- 4. event_preview(id): anonymous event-page header fields
-- ------------------------------------------------------------
-- Key set is the contract in medconf-website/src/lib/event-public.ts
-- (PublicEventFields). NULL when the row is archived or missing.
-- description_excerpt: whitespace-collapsed, first 300 characters.
CREATE OR REPLACE FUNCTION public.event_preview(p_id integer)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT jsonb_build_object(
    'id', c.id,
    'conference_name', c.conference_name,
    'specialty', c.specialty,
    'event_type', c.event_type,
    'event_format', c.event_format,
    'is_flagship', COALESCE(c.is_flagship, FALSE),
    'is_on_demand', COALESCE(c.is_on_demand, FALSE),
    'start_date', c.start_date,
    'end_date', c.end_date,
    'city', c.city,
    'region', c.region,
    'society', s.society,
    'description_excerpt', NULLIF(left(btrim(regexp_replace(COALESCE(c.description, ''), '\s+', ' ', 'g')), 300), '')
  )
  FROM public.conferences c
  LEFT JOIN public.scraper_sources s ON s.id = c.source_id
  WHERE c.id = p_id AND c.archived = FALSE;
$$;

REVOKE ALL ON FUNCTION public.event_preview(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.event_preview(integer) TO anon, authenticated;

-- ------------------------------------------------------------
-- 5. sitemap_events(): ids + freshness only
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sitemap_events()
RETURNS TABLE(id integer, updated_at timestamptz)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT c.id, c.updated_at
  FROM public.conferences c
  WHERE c.archived = FALSE
  ORDER BY c.updated_at DESC NULLS LAST, c.id DESC
  LIMIT 5000;
$$;

REVOKE ALL ON FUNCTION public.sitemap_events() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sitemap_events() TO anon, authenticated;
