-- 2026-11-20: EHA Congress 165 back on, fetching ehaweb.org with the honest MedConfBot agent
-- (owner authorised 2026-11-14). Reverses _deactivate_165.sql.
UPDATE public.scraper_sources SET active = TRUE WHERE id = 165;
