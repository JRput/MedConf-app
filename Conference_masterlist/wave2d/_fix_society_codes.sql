-- Wave 2d follow-up (2026-10-22): normalise scraper_sources.society to SHORT codes.
-- `society` is the directory filter chip label and the `?society=` URL value, and
-- the key of medconf-website/src/lib/taxonomy/societies.ts. Batches A, D and C2
-- were registered with full names; every other source uses an acronym/short brand.
-- directory_events joins scraper_sources.society live, so no conference rows change.
UPDATE public.scraper_sources SET society = 'BSSH'             WHERE id = 116 AND society = 'British Society for Surgery of the Hand';
UPDATE public.scraper_sources SET society = 'Vascular Society' WHERE id = 117 AND society = 'Vascular Society of Great Britain & Ireland';
UPDATE public.scraper_sources SET society = 'BAUS'             WHERE id = 118 AND society = 'British Association of Urological Surgeons';
UPDATE public.scraper_sources SET society = 'HIS'              WHERE id = 119 AND society = 'Healthcare Infection Society';
UPDATE public.scraper_sources SET society = 'BBTS'             WHERE id = 120 AND society = 'British Blood Transfusion Society';
UPDATE public.scraper_sources SET society = 'ABS'              WHERE id = 121 AND society = 'Association of Breast Surgery';
UPDATE public.scraper_sources SET society = 'BASL'             WHERE id = 122 AND society = 'British Association for the Study of the Liver';
UPDATE public.scraper_sources SET society = 'BSG'              WHERE id = 130 AND society = 'British Society of Gastroenterology';
UPDATE public.scraper_sources SET society = 'BOA'              WHERE id = 131 AND society = 'British Orthopaedic Association';
UPDATE public.scraper_sources SET society = 'ICS'              WHERE id = 133 AND society = 'Intensive Care Society';
UPDATE public.scraper_sources SET society = 'ASH'              WHERE id = 139 AND society = 'American Society of Hematology (ASH)';
UPDATE public.scraper_sources SET society = 'AAN'              WHERE id = 140 AND society = 'American Academy of Neurology (AAN)';
UPDATE public.scraper_sources SET society = 'AAD'              WHERE id = 141 AND society = 'American Academy of Dermatology (AAD)';
UPDATE public.scraper_sources SET society = 'CNS'              WHERE id = 142 AND society = 'Congress of Neurological Surgeons (CNS)';
UPDATE public.scraper_sources SET society = 'AUGIS'            WHERE id = 143 AND society = 'Association of Upper Gastrointestinal Surgeons of GB&I (AUGIS)';
