-- 2026-11-14: EHA Congress 165 inactive until the owner decides how to fetch ehaweb.org (runner gets 403 with the browser-style agent; fix path needs the owner's explicit go). Reversible: UPDATE ... SET active = TRUE.
UPDATE public.scraper_sources SET active = FALSE WHERE id = 165;
