-- Rollback of 20261027000000_event_type_degree.sql. Not applied automatically.
-- Reversible: the ids of every 'degree' row are recorded in
-- public.event_type_rollback_degree_ids BEFORE they change, so the forward
-- migration + backfill can be replayed from that table if the rollback itself is undone.
-- Rows the backfill changed return to their previous type; any other 'degree'
-- row (emitted later by the scraper) goes to 'course'.
-- Apply AFTER the scraper code that emits 'degree' is reverted/stopped.

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS public.event_type_rollback_degree_ids (
  conference_id INTEGER PRIMARY KEY,
  restored_to TEXT NOT NULL,
  rolled_back_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.event_type_rollback_degree_ids ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.event_type_rollback_degree_ids FROM PUBLIC, anon, authenticated;

DO $$
BEGIN
  IF to_regclass('public.event_type_degree_backfill') IS NOT NULL THEN
    INSERT INTO public.event_type_rollback_degree_ids (conference_id, restored_to)
    SELECT c.id, COALESCE(b.prev_event_type, 'course')
      FROM public.conferences c
      LEFT JOIN public.event_type_degree_backfill b ON b.conference_id = c.id
     WHERE c.event_type = 'degree'
    ON CONFLICT (conference_id) DO UPDATE SET restored_to = EXCLUDED.restored_to, rolled_back_at = NOW();
  ELSE
    INSERT INTO public.event_type_rollback_degree_ids (conference_id, restored_to)
    SELECT id, 'course' FROM public.conferences WHERE event_type = 'degree'
    ON CONFLICT (conference_id) DO UPDATE SET restored_to = EXCLUDED.restored_to, rolled_back_at = NOW();
  END IF;
END $$;

UPDATE public.conferences c SET event_type = r.restored_to
  FROM public.event_type_rollback_degree_ids r
 WHERE c.id = r.conference_id AND c.event_type = 'degree';

UPDATE public.scraper_sources SET default_event_type = 'course' WHERE default_event_type = 'degree';

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'public.conferences'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%event_type = ANY%' LOOP
    EXECUTE format('ALTER TABLE public.conferences DROP CONSTRAINT %I', r.conname);
  END LOOP;
  ALTER TABLE public.conferences ADD CONSTRAINT conferences_event_type_check
    CHECK (event_type IN ('conference','workshop','course'));
  FOR r IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'public.scraper_sources'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%default_event_type = ANY%' LOOP
    EXECUTE format('ALTER TABLE public.scraper_sources DROP CONSTRAINT %I', r.conname);
  END LOOP;
  ALTER TABLE public.scraper_sources ADD CONSTRAINT scraper_sources_default_event_type_check
    CHECK (default_event_type IN ('conference','workshop','course','mixed'));
END $$;

DROP FUNCTION IF EXISTS public.is_degree_title(text);
-- Kept on purpose (audit trail, tiny, service-only): event_type_degree_backfill,
-- event_type_rollback_degree_ids. Drop them by hand once the rollback is final.
