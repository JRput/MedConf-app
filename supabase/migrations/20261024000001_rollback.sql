-- ============================================================
-- EMERGENCY ROLLBACK if production reads break after applying
-- 20261024000001_access_gate_phase2.sql. Restores anonymous read access
-- exactly as it was before (policy names, predicates, grants). Drops nothing
-- else: home_preview(), event_preview(integer) and sitemap_events() may stay.
-- Run via: cd medconf-scraper && ./.venv/bin/python apply_migration.py \
--            ../supabase/migrations/20261024000001_rollback.sql
-- Idempotent.
-- ============================================================

DROP POLICY IF EXISTS "Authenticated can view conferences" ON public.conferences;
DROP POLICY IF EXISTS "Anyone can view conferences" ON public.conferences;
CREATE POLICY "Anyone can view conferences"
    ON public.conferences FOR SELECT
    USING (archived = FALSE);

DROP POLICY IF EXISTS "Authenticated can view pricing tiers" ON public.pricing_tiers;
DROP POLICY IF EXISTS "Anyone can view pricing tiers" ON public.pricing_tiers;
CREATE POLICY "Anyone can view pricing tiers"
    ON public.pricing_tiers FOR SELECT
    USING (TRUE);

DROP POLICY IF EXISTS "Authenticated can view course sessions" ON public.course_sessions;
DROP POLICY IF EXISTS "Anyone can view course sessions" ON public.course_sessions;
CREATE POLICY "Anyone can view course sessions"
    ON public.course_sessions FOR SELECT
    USING (TRUE);

DROP POLICY IF EXISTS "Authenticated can view scraper sources" ON public.scraper_sources;
DROP POLICY IF EXISTS "Anyone can view scraper sources" ON public.scraper_sources;
CREATE POLICY "Anyone can view scraper sources"
    ON public.scraper_sources FOR SELECT
    USING (TRUE);

DROP POLICY IF EXISTS "Published facts are visible to authenticated" ON public.community_facts;
DROP POLICY IF EXISTS "Published facts are public" ON public.community_facts;
CREATE POLICY "Published facts are public"
    ON public.community_facts FOR SELECT
    USING (is_published OR public.is_admin());

DROP POLICY IF EXISTS "Published tiers are visible to authenticated" ON public.community_tiers;
DROP POLICY IF EXISTS "Published tiers are public" ON public.community_tiers;
CREATE POLICY "Published tiers are public"
    ON public.community_tiers FOR SELECT
    USING (is_published OR public.is_admin());

GRANT SELECT ON public.community_facts, public.community_tiers TO anon, authenticated;
GRANT SELECT ON public.directory_events TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.directory_facets(
  text, date, date, text[], text[], text[], text[], text, text, text[], boolean, boolean
) TO PUBLIC, anon, authenticated;
