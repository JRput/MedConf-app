// src/lib/taxonomy/specialties.ts
//
// `conferences.specialty` is free text filled in by the scraper's
// heuristic classifier (see medconf-scraper/extractors/specialty_classifier.py)
// — 130+ distinct raw values as of 2026-10, with heavy near-duplication
// (UK/US spelling, "&" vs "and", singular/plural, parenthetical variants).
// See ../../../../reports/website-audit/data.md §5 for the source audit
// this map completes.
//
// The DB column itself is never rewritten — the scraper's output stays raw
// so a wrong canonicalisation here is a one-file fix, not a backfill.
// Filtering by a parent specialty therefore means: look up every raw value
// that maps to that parent, then query `specialty IN (...)` with the raw
// values (see `expandSpecialtyFilter` in ../directory-query.ts). This file
// is the only place that mapping lives.

export interface SpecialtyParent {
  slug: string
  label: string
  order: number
}

// ~20-25 was the audit's target; the live data's genuine subspecialty spread
// (130 raw values across UK royal colleges + 9 international oncology
// societies) settles at 28 parents plus "other" — fewer would flatten
// clinically distinct filters (e.g. folding Cardiology into "Medicine").
export const SPECIALTY_PARENTS: SpecialtyParent[] = [
  { slug: 'general-practice', label: 'General Practice', order: 1 },
  { slug: 'medicine-general', label: 'General & Internal Medicine', order: 2 },
  { slug: 'oncology', label: 'Oncology', order: 3 },
  { slug: 'paediatrics', label: 'Paediatrics', order: 4 },
  { slug: 'surgery-general', label: 'General & Minor Surgery', order: 5 },
  { slug: 'anaesthetics-critical-care', label: 'Anaesthetics & Critical Care', order: 6 },
  { slug: 'emergency-medicine', label: 'Emergency Medicine', order: 7 },
  { slug: 'cardiology', label: 'Cardiology', order: 8 },
  { slug: 'radiology-imaging', label: 'Radiology & Imaging', order: 9 },
  { slug: 'psychiatry-mental-health', label: 'Psychiatry & Mental Health', order: 10 },
  { slug: 'obgyn-womens-health', label: "Obstetrics, Gynaecology & Women's Health", order: 11 },
  { slug: 'msk-trauma-orthopaedics', label: 'Musculoskeletal, Trauma & Orthopaedics', order: 12 },
  { slug: 'haematology', label: 'Haematology', order: 13 },
  { slug: 'pathology-laboratory-medicine', label: 'Pathology & Laboratory Medicine', order: 14 },
  { slug: 'gastroenterology', label: 'Gastroenterology', order: 15 },
  { slug: 'neurology-neurosurgery', label: 'Neurology & Neurosurgery', order: 16 },
  { slug: 'respiratory-medicine', label: 'Respiratory Medicine', order: 17 },
  { slug: 'endocrinology-diabetes', label: 'Endocrinology & Diabetes', order: 18 },
  { slug: 'urology', label: 'Urology', order: 19 },
  { slug: 'ophthalmology', label: 'Ophthalmology', order: 20 },
  { slug: 'ent-otolaryngology', label: 'ENT / Otolaryngology', order: 21 },
  { slug: 'dermatology', label: 'Dermatology', order: 22 },
  { slug: 'dentistry-oral-maxillofacial', label: 'Dentistry & Oral-Maxillofacial', order: 23 },
  { slug: 'geriatric-medicine', label: 'Geriatric Medicine', order: 24 },
  { slug: 'palliative-rehabilitation', label: 'Palliative Care & Rehabilitation', order: 25 },
  { slug: 'infectious-disease-immunology', label: 'Infectious Disease & Immunology', order: 26 },
  { slug: 'public-health', label: 'Public Health & Occupational Medicine', order: 27 },
  { slug: 'leadership-management', label: 'Leadership, Management & Professional Practice', order: 28 },
  { slug: 'medical-education', label: 'Medical Education & Exams', order: 29 },
  { slug: 'research-digital-health', label: 'Research & Digital Health', order: 30 },
  { slug: 'allied-health-nursing', label: 'Nursing & Allied Health', order: 31 },
  { slug: 'other', label: 'Other', order: 99 },
]

const PARENT_LABEL: Record<string, string> = Object.fromEntries(
  SPECIALTY_PARENTS.map((p) => [p.slug, p.label])
)

/**
 * Raw `conferences.specialty` value → canonical parent slug.
 * Every one of the 130 raw values observed live (2026-10 pull) is listed.
 * Keys are matched case-sensitively as stored; `canonicalSpecialty` below
 * lowercases for lookup so future drift in casing doesn't silently fall
 * through to "other".
 */
export const RAW_TO_CANONICAL: Record<string, string> = {
  // General Practice
  'General Practice': 'general-practice',
  'GP Training': 'general-practice',

  // General & Internal Medicine
  'General Medicine': 'medicine-general',
  'General Internal Medicine': 'medicine-general',
  'Internal Medicine': 'medicine-general',
  'Acute Medicine': 'medicine-general',
  'Rheumatology': 'medicine-general',
  'General': 'medicine-general',

  // Oncology
  'Oncology': 'oncology',
  'Clinical Oncology': 'oncology',
  'Surgical Oncology': 'oncology',
  'Gynaecological Oncology': 'oncology',
  'Cardio-Oncology': 'oncology',
  'Biomarker Research': 'oncology',

  // Paediatrics
  'Paediatrics': 'paediatrics',
  'Paediatric Surgery': 'paediatrics',
  'Paediatric Neurology': 'paediatrics',
  'Neurodevelopmental Disorders': 'paediatrics',

  // General & Minor Surgery
  'General Surgery': 'surgery-general',
  'Surgery': 'surgery-general',
  'Surgery (General)': 'surgery-general',
  'Surgery (RCS)': 'surgery-general',
  'Minor Surgery': 'surgery-general',
  'Minor Surgery & Procedures': 'surgery-general',
  'Emergency General Surgery': 'surgery-general',
  'Minimal Access Surgery': 'surgery-general',
  'Craniofacial Surgery': 'surgery-general',
  'Vascular Surgery': 'surgery-general',
  'Colorectal Surgery': 'surgery-general',

  // Anaesthetics & Critical Care
  'Anaesthetics': 'anaesthetics-critical-care',
  'Intensive Care Medicine': 'anaesthetics-critical-care',
  'Pain Management': 'anaesthetics-critical-care',

  // Emergency Medicine
  'Emergency Medicine': 'emergency-medicine',
  'Urgent Care': 'emergency-medicine',
  'Trauma': 'emergency-medicine',

  // Cardiology
  'Cardiology': 'cardiology',
  'Cardiovascular Nursing': 'cardiology',
  'Acute Heart Failure': 'cardiology',
  'Heart Failure': 'cardiology',
  'Interventional Cardiology and Cardiovascular Surgery': 'cardiology',
  'Preventive Cardiology': 'cardiology',
  'e-Cardiology and Digital Health': 'cardiology',
  '心血管内科': 'cardiology',

  // Radiology & Imaging
  'Radiology': 'radiology-imaging',
  'Imaging': 'radiology-imaging',
  'Dental and Maxillofacial Radiology': 'radiology-imaging',
  'Dentistry and Maxillofacial Imaging': 'radiology-imaging',

  // Psychiatry & Mental Health
  'Psychiatry': 'psychiatry-mental-health',
  'Child and Adolescent Psychiatry': 'psychiatry-mental-health',
  'Forensic Psychiatry': 'psychiatry-mental-health',
  'Perinatal Psychiatry': 'psychiatry-mental-health',
  'Neuropsychiatry': 'psychiatry-mental-health',
  'Mental Health': 'psychiatry-mental-health',
  'Psychotherapy': 'psychiatry-mental-health',

  // Obstetrics, Gynaecology & Women's Health
  'Obstetrics & Gynaecology': 'obgyn-womens-health',
  'Obstetrics and Gynaecology': 'obgyn-womens-health',
  'Obstetrics and Gynecology': 'obgyn-womens-health',
  "Women's Health": 'obgyn-womens-health',
  'Sexual and Reproductive Health': 'obgyn-womens-health',
  'Sexual & Reproductive Health': 'obgyn-womens-health',

  // Musculoskeletal, Trauma & Orthopaedics
  'Musculoskeletal & Trauma': 'msk-trauma-orthopaedics',
  'Orthopaedics': 'msk-trauma-orthopaedics',
  'Trauma & Orthopaedics': 'msk-trauma-orthopaedics',
  'Orthopaedic Surgery': 'msk-trauma-orthopaedics',

  // Haematology
  'Haematology': 'haematology',
  'Haematopathology': 'haematology',

  // Pathology & Laboratory Medicine
  'Pathology': 'pathology-laboratory-medicine',
  'Histopathology': 'pathology-laboratory-medicine',
  'Forensic Pathology': 'pathology-laboratory-medicine',
  'Surgical Pathology': 'pathology-laboratory-medicine',
  'Breast Pathology': 'pathology-laboratory-medicine',
  'Laboratory Medicine': 'pathology-laboratory-medicine',

  // Gastroenterology
  'Gastroenterology': 'gastroenterology',
  'Gastroenterology & Hepatology': 'gastroenterology',

  // Neurology & Neurosurgery
  'Neurology': 'neurology-neurosurgery',
  'Neurosurgery': 'neurology-neurosurgery',

  // Respiratory Medicine
  'Respiratory': 'respiratory-medicine',
  'Respiratory Medicine': 'respiratory-medicine',

  // Endocrinology & Diabetes
  'Diabetes & Endocrinology': 'endocrinology-diabetes',
  'Endocrinology': 'endocrinology-diabetes',

  // Urology
  'Urology': 'urology',
  'Uropathology': 'urology',

  // Ophthalmology
  'Ophthalmology': 'ophthalmology',
  'Vision Research': 'ophthalmology',

  // ENT / Otolaryngology
  'ENT': 'ent-otolaryngology',
  'Otolaryngology': 'ent-otolaryngology',
  'Otolaryngology (ENT)': 'ent-otolaryngology',
  'ENT Surgery': 'ent-otolaryngology',

  // Dermatology
  'Dermatology': 'dermatology',
  'Aesthetic & Cosmetic Medicine': 'dermatology',

  // Dentistry & Oral-Maxillofacial
  'Dentistry': 'dentistry-oral-maxillofacial',
  'Orthodontics': 'dentistry-oral-maxillofacial',
  'Oral and Maxillofacial Surgery': 'dentistry-oral-maxillofacial',

  // Geriatric Medicine
  'Geriatric Medicine': 'geriatric-medicine',
  'Geriatrics': 'geriatric-medicine',

  // Palliative Care & Rehabilitation
  'Palliative Medicine': 'palliative-rehabilitation',
  'Palliative Care': 'palliative-rehabilitation',
  'Rehabilitation': 'palliative-rehabilitation',
  'Rehabilitation Medicine': 'palliative-rehabilitation',
  'Sleep Medicine': 'palliative-rehabilitation',

  // Infectious Disease & Immunology
  'Microbiology': 'infectious-disease-immunology',
  'Infectious Disease': 'infectious-disease-immunology',
  'HIV Medicine': 'infectious-disease-immunology',
  'HIV Prevention Research': 'infectious-disease-immunology',
  'Immunology': 'infectious-disease-immunology',
  'Allergy & Immunology': 'infectious-disease-immunology',
  'Infection Prevention and Control': 'infectious-disease-immunology',

  // Public Health & Occupational Medicine
  'Public Health': 'public-health',
  'Occupational Medicine': 'public-health',
  'Preventive Medicine': 'public-health',
  'Travel Medicine': 'public-health',

  // Leadership, Management & Professional Practice
  'Leadership & Management': 'leadership-management',
  'Medical Leadership': 'leadership-management',
  'Faculty & Networking': 'leadership-management',
  'Finance & Pensions': 'leadership-management',
  'Risk Management': 'leadership-management',
  'Medico-Legal': 'leadership-management',
  'Professionalism & Ethics': 'leadership-management',
  'Wellbeing': 'leadership-management',

  // Medical Education & Exams
  'Medical Education': 'medical-education',
  'Exam Preparation': 'medical-education',

  // Research & Digital Health
  'Research': 'research-digital-health',
  'Artificial Intelligence in Medicine': 'research-digital-health',
  'Digital Health': 'research-digital-health',
  'Clinical Pharmacology': 'research-digital-health',
  'Pharmaceutical Medicine': 'research-digital-health',

  // Nursing & Allied Health
  'Nursing': 'allied-health-nursing',
  'Podiatry': 'allied-health-nursing',

  // Other / unclassified
  'None': 'other',
}

export interface CanonicalSpecialty {
  parent: string
  label: string
}

/**
 * Map a raw `specialty` string to its canonical parent slug + label.
 * Case-insensitive lookup; unmapped or null values fall through to "other"
 * rather than throwing, so a new raw value from a newly-onboarded source
 * never breaks the filter UI — it just shows up under Other until this
 * map is updated.
 */
export function canonicalSpecialty(raw: string | null | undefined): CanonicalSpecialty {
  if (!raw) return { parent: 'other', label: PARENT_LABEL.other }
  const direct = RAW_TO_CANONICAL[raw]
  if (direct) return { parent: direct, label: PARENT_LABEL[direct] }
  // Case-insensitive fallback for stray casing drift from the scraper.
  const lower = raw.toLowerCase()
  const entry = Object.entries(RAW_TO_CANONICAL).find(([k]) => k.toLowerCase() === lower)
  if (entry) return { parent: entry[1], label: PARENT_LABEL[entry[1]] }
  return { parent: 'other', label: PARENT_LABEL.other }
}

/**
 * All raw specialty values that canonicalise to `parentSlug`. Used by
 * directory-query.ts to expand a parent-slug filter into a Postgres
 * `specialty IN (...)` list, since the DB column stores raw values only.
 */
export function rawValuesForParent(parentSlug: string): string[] {
  return Object.entries(RAW_TO_CANONICAL)
    .filter(([, parent]) => parent === parentSlug)
    .map(([raw]) => raw)
}
