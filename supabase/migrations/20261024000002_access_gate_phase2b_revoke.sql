-- ============================================================
-- Access gate, Phase 2b of 2b (2026-10-24): STEP 2 OF 2 - apply AFTER the
-- website deploy that reads the preview functions is live. Board:
-- MISSION_BOARD_ACCESS_GATE.md.
--
-- Requires 20261024000001_access_gate_phase2a_functions.sql to be applied
-- first. DEPLOY ORDER WARNING: applying this before the website code that
-- calls home_preview / event_preview / sitemap_events is live breaks every
-- anonymous page (production reads anon data until then).
--
-- What changes:
--   * SELECT policies on conferences, pricing_tiers, course_sessions,
--     scraper_sources, community_facts, community_tiers become TO authenticated
--     (same predicates). Write policies and service_role are untouched
--     (service_role bypasses RLS).
--   * anon loses SELECT on directory_events and EXECUTE on directory_facets.
--     Postgres grants EXECUTE on new functions to PUBLIC by default, so the
--     revoke names PUBLIC too; otherwise anon would keep access through it.
--
-- Checks: 20261024000002_checks.txt. After applying, smoke anonymous /,
-- /conferences/<id>, /sitemap.xml and signed-in /conferences. On failure run
-- 20261024000002_rollback.sql via the same tool.
-- Idempotent: DROP POLICY IF EXISTS / CREATE POLICY / REVOKE / GRANT.
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

