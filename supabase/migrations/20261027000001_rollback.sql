-- Rollback of 20261027000001_remediator_replace_tiers.sql (function only; no data was created).
DROP FUNCTION IF EXISTS public.remediator_replace_tiers_if_zero_or_generic(bigint, jsonb);
