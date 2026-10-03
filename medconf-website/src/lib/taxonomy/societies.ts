// src/lib/taxonomy/societies.ts
//
// Map from `scraper_sources.society` short code → display metadata.
// Pulled from a live read of `scraper_sources` (44 active rows, ids 1-45
// skipping 40) on 2026-10-02 via the public anon-key SELECT — the table has
// a public-read RLS policy (see supabase_schema.sql's "Anyone can view
// scraper sources"). Several sources share one society code (RCEM has 3
// rows, RCSEng 2, RCOG 2, RCR 2, ASCO 2, ESGO 2) — this map is keyed by
// the society code, not the source row, which is exactly what lets the
// directory fold them into one filter chip (the pattern `useConferences.ts`
// already uses for `society` vs `sourceId`).
//
// When a new source is onboarded (see extractors/PLAYBOOK.md), add its
// `society` code here too, or it'll render with no full name / grouping in
// the society filter until this file is updated.

export type SocietyKind = 'royal-college' | 'faculty' | 'specialist' | 'international' | 'defence' | 'other'

export interface SocietyInfo {
  short: string
  name: string
  kind: SocietyKind
  country: string // ISO-ish short label; 'International' for multi-country societies
}

export const SOCIETIES: Record<string, SocietyInfo> = {
  RCGP: { short: 'RCGP', name: 'Royal College of General Practitioners', kind: 'royal-college', country: 'UK' },
  RCSEng: { short: 'RCSEng', name: 'Royal College of Surgeons of England', kind: 'royal-college', country: 'UK' },
  RSM: { short: 'RSM', name: 'Royal Society of Medicine', kind: 'specialist', country: 'UK' },
  RCP: { short: 'RCP', name: 'Royal College of Physicians', kind: 'royal-college', country: 'UK' },
  RCEM: { short: 'RCEM', name: 'Royal College of Emergency Medicine', kind: 'royal-college', country: 'UK' },
  RCOG: { short: 'RCOG', name: 'Royal College of Obstetricians and Gynaecologists', kind: 'royal-college', country: 'UK' },
  RCR: { short: 'RCR', name: 'Royal College of Radiologists', kind: 'royal-college', country: 'UK' },
  BOPA: { short: 'BOPA', name: 'British Oncology Pharmacy Association', kind: 'specialist', country: 'UK' },
  BTOG: { short: 'BTOG', name: 'British Thoracic Oncology Group', kind: 'specialist', country: 'UK' },
  ASCO: { short: 'ASCO', name: 'American Society of Clinical Oncology', kind: 'international', country: 'US' },
  ESMO: { short: 'ESMO', name: 'European Society for Medical Oncology', kind: 'international', country: 'International' },
  AACR: { short: 'AACR', name: 'American Association for Cancer Research', kind: 'international', country: 'US' },
  ESTRO: { short: 'ESTRO', name: 'European Society for Radiotherapy and Oncology', kind: 'international', country: 'International' },
  SABCS: { short: 'SABCS', name: 'San Antonio Breast Cancer Symposium', kind: 'international', country: 'US' },
  ESGO: { short: 'ESGO', name: 'European Society of Gynaecological Oncology', kind: 'international', country: 'International' },
  SITC: { short: 'SITC', name: 'Society for Immunotherapy of Cancer', kind: 'international', country: 'US' },
  ALSG: { short: 'ALSG', name: 'Advanced Life Support Group', kind: 'specialist', country: 'UK' },
  RCPSG: { short: 'RCPSG', name: 'Royal College of Physicians and Surgeons of Glasgow', kind: 'royal-college', country: 'UK' },
  RCPath: { short: 'RCPath', name: 'Royal College of Pathologists', kind: 'royal-college', country: 'UK' },
  RCPsych: { short: 'RCPsych', name: 'Royal College of Psychiatrists', kind: 'royal-college', country: 'UK' },
  RCSEd: { short: 'RCSEd', name: 'Royal College of Surgeons of Edinburgh', kind: 'royal-college', country: 'UK' },
  'Resus Council UK': { short: 'Resus Council UK', name: 'Resuscitation Council UK', kind: 'specialist', country: 'UK' },
  RCPE: { short: 'RCPE', name: 'Royal College of Physicians of Edinburgh', kind: 'royal-college', country: 'UK' },
  RCPCH: { short: 'RCPCH', name: 'Royal College of Paediatrics and Child Health', kind: 'royal-college', country: 'UK' },
  RCOphth: { short: 'RCOphth', name: 'Royal College of Ophthalmologists', kind: 'royal-college', country: 'UK' },
  FPH: { short: 'FPH', name: 'Faculty of Public Health', kind: 'faculty', country: 'UK' },
  FOM: { short: 'FOM', name: 'Faculty of Occupational Medicine', kind: 'faculty', country: 'UK' },
  FPM: { short: 'FPM', name: 'Faculty of Pharmaceutical Medicine', kind: 'faculty', country: 'UK' },
  ESC: { short: 'ESC', name: 'European Society of Cardiology', kind: 'international', country: 'International' },
  ACPGBI: { short: 'ACPGBI', name: 'Association of Coloproctology of Great Britain and Ireland', kind: 'specialist', country: 'UK' },
  ASGBI: { short: 'ASGBI', name: 'Association of Surgeons of Great Britain and Ireland', kind: 'specialist', country: 'UK' },
  CoSRH: { short: 'CoSRH', name: 'College of Sexual and Reproductive Healthcare', kind: 'specialist', country: 'UK' },
  FICM: { short: 'FICM', name: 'Faculty of Intensive Care Medicine', kind: 'faculty', country: 'UK' },
  ARVO: { short: 'ARVO', name: 'Association for Research in Vision and Ophthalmology', kind: 'international', country: 'US' },
  IAS: { short: 'IAS', name: 'International AIDS Society', kind: 'international', country: 'International' },
  MDDUS: { short: 'MDDUS', name: 'Medical and Dental Defence Union of Scotland', kind: 'defence', country: 'UK' },
  MDU: { short: 'MDU', name: 'Medical Defence Union', kind: 'defence', country: 'UK' },
}

export function societyInfo(short: string | null | undefined): SocietyInfo | null {
  if (!short) return null
  return SOCIETIES[short] ?? null
}

/** Grouped by `kind`, for a faceted society filter (royal colleges first, etc). */
export function societiesByKind(): Record<SocietyKind, SocietyInfo[]> {
  const out: Record<SocietyKind, SocietyInfo[]> = {
    'royal-college': [],
    faculty: [],
    specialist: [],
    international: [],
    defence: [],
    other: [],
  }
  for (const s of Object.values(SOCIETIES)) out[s.kind].push(s)
  for (const k of Object.keys(out) as SocietyKind[]) out[k].sort((a, b) => a.name.localeCompare(b.name))
  return out
}
