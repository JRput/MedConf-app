-- ============================================================
-- Community Contributions — privilege check fix (2026-10-18)
-- Inside a SECURITY DEFINER function current_user is the function OWNER
-- (postgres), so is_privileged_caller() as written in 20261018000001
-- returned TRUE for every caller of moderate_contribution() /
-- expire_stale_contributions(). session_user is not changed by a
-- SECURITY DEFINER switch: PostgREST sessions are 'authenticator',
-- direct owner sessions (pooler, dashboard) are 'postgres'.
-- Also: length caps on the private note / evidence columns, and no
-- EXECUTE for anon on the moderation RPCs.
-- ============================================================

CREATE OR REPLACE FUNCTION public.is_privileged_caller()
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT COALESCE(auth.role() = 'service_role', FALSE)
      OR session_user IN ('postgres', 'supabase_admin')
$$;

ALTER TABLE community_contributions DROP CONSTRAINT IF EXISTS community_contributions_note_len;
ALTER TABLE community_contributions ADD CONSTRAINT community_contributions_note_len
  CHECK (note IS NULL OR length(note) <= 1000);
ALTER TABLE community_contributions DROP CONSTRAINT IF EXISTS community_contributions_evidence_len;
ALTER TABLE community_contributions ADD CONSTRAINT community_contributions_evidence_len
  CHECK (evidence_url IS NULL OR length(evidence_url) <= 2048);

REVOKE EXECUTE ON FUNCTION public.moderate_contribution(UUID, TEXT, TEXT, JSONB) FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.expire_stale_contributions() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.moderate_contribution(UUID, TEXT, TEXT, JSONB) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.expire_stale_contributions() TO authenticated, service_role;
