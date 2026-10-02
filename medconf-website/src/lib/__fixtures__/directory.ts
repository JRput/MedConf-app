// src/lib/__fixtures__/directory.ts
//
// Thin dev fixture for the W2b directory UI build. The real data path is
// `directory_events` + `directory_facets()` (see directory-query.ts), added
// by supabase/migrations/20261002000000_directory_query_layer.sql — which at
// the time this file was written had not yet been applied to the live
// project (PGRST205 "directory_events not found"). This fixture lets the UI
// be built and visually verified against realistic data in the meantime.
//
// Switched on by `?fixture=1` on /api/directory or the page route, or by
// NEXT_PUBLIC_DIRECTORY_FIXTURE=1. See src/lib/directory-source.ts, which is
// the ONLY place that branches between this file and the real Supabase
// query path — delete that branch (and this file) once the migration is
// confirmed live everywhere.
//
// ~40 rows, derived from the shapes in src/app/design/sample-data.ts, spread
// across enough societies/specialties/regions/prices/formats/types that
// every filter and facet in the sidebar has something real to show.

import type { DirectoryEvent } from '../directory'
import {
  DEFAULT_FILTERS,
  classifyPriceBucket,
  resolveDatePreset,
  type DirectoryFacets,
  type DirectoryFilters,
  type DirectoryPage,
} from '../directory-query'
import { canonicalSpecialty } from '../taxonomy/specialties'

function inDays(n: number): string {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

interface Seed {
  name: string
  specialty: string | null
  eventType: DirectoryEvent['eventType']
  isFlagship?: boolean
  isOnDemand?: boolean
  isSoldOut?: boolean
  startIn: number
  endIn?: number
  format: DirectoryEvent['format']
  city: string | null
  region: string | null
  country: 'uk' | 'international'
  society: string
  priceMin: number | null
  priceMax?: number | null
  currency?: string
  cpdAccredited?: boolean
  cpdPoints?: number | null
  abstractDeadlineIn?: number | null
  abstractDeadlineNote?: string | null
  abstractOpen?: boolean
}

const SEEDS: Seed[] = [
  { name: 'South West Autumn Conference — Delusions, dopaminergic medications and eating disorders', specialty: 'Psychiatry', eventType: 'conference', startIn: 44, format: 'in_person', city: 'Bristol', region: 'South West', country: 'uk', society: 'RCPsych', priceMin: 28, priceMax: 208, cpdAccredited: true, cpdPoints: 5, abstractDeadlineIn: 6, abstractOpen: true },
  { name: 'ASCO Annual Meeting 2027 — Advancing Equitable Cancer Care', specialty: 'Oncology', eventType: 'conference', isFlagship: true, startIn: 212, endIn: 215, format: 'hybrid', city: 'Chicago', region: 'Illinois', country: 'international', society: 'ASCO', priceMin: 795, priceMax: 1450, currency: 'USD', cpdAccredited: true, abstractDeadlineIn: 96, abstractOpen: true },
  { name: 'Basic Surgical Skills — two-day intensive', specialty: 'General Surgery', eventType: 'course', isSoldOut: true, startIn: 19, endIn: 20, format: 'in_person', city: 'London', region: 'London', country: 'uk', society: 'RCSEng', priceMin: 720, priceMax: 720, cpdAccredited: true, cpdPoints: 12 },
  { name: 'Recognising sepsis in the deteriorating child: an evening webinar', specialty: 'Paediatrics', eventType: 'workshop', startIn: 9, format: 'online', city: null, region: null, country: 'uk', society: 'RCPCH', priceMin: 0, cpdAccredited: true, cpdPoints: 1 },
  { name: 'ESMO Congress 2027', specialty: 'Medical Oncology', eventType: 'conference', isFlagship: true, startIn: 378, endIn: 382, format: 'in_person', city: 'Madrid', region: 'International', country: 'international', society: 'ESMO', priceMin: 640, priceMax: 1180, currency: 'EUR', cpdAccredited: true, cpdPoints: 32, abstractDeadlineIn: 2, abstractOpen: true },
  { name: 'Emergency Medicine Educators Day', specialty: 'Emergency Medicine', eventType: 'conference', startIn: 36, format: 'online', city: null, region: null, country: 'uk', society: 'RCEM', priceMin: 185, priceMax: 555, cpdAccredited: true, cpdPoints: 5, abstractDeadlineNote: 'see event page for details', abstractOpen: true },
  { name: 'Catch-up: Winter pressures and acute medical take — recorded sessions', specialty: 'Acute Medicine', eventType: 'conference', isOnDemand: true, startIn: 12, format: 'online', city: null, region: null, country: 'uk', society: 'RCP', priceMin: 45, priceMax: 45 },
  { name: 'Obstetric anaesthesia: simulation and human factors masterclass', specialty: 'Anaesthetics', eventType: 'workshop', startIn: 88, format: 'in_person', city: 'Manchester', region: 'North West', country: 'uk', society: 'RCoA', priceMin: null },
  { name: 'AACR Annual Meeting 2027', specialty: 'Oncology', eventType: 'conference', isFlagship: true, startIn: 198, endIn: 202, format: 'hybrid', city: 'San Diego', region: 'California', country: 'international', society: 'AACR', priceMin: 850, priceMax: 1600, currency: 'USD', cpdAccredited: true, abstractDeadlineIn: 45, abstractOpen: true },
  { name: 'Radiology Masterclass: MSK Imaging Update', specialty: 'Radiology', eventType: 'conference', startIn: 61, format: 'in_person', city: 'Leeds', region: 'Yorkshire', country: 'uk', society: 'RCR', priceMin: 165, priceMax: 310, cpdAccredited: true, cpdPoints: 6 },
  { name: 'RCOG World Congress 2027', specialty: "Obstetrics & Gynaecology", eventType: 'conference', isFlagship: true, startIn: 290, endIn: 293, format: 'in_person', city: 'Cape Town', region: 'International', country: 'international', society: 'RCOG', priceMin: 420, priceMax: 890, currency: 'USD', cpdAccredited: true, abstractDeadlineIn: 70, abstractOpen: true },
  { name: 'Cardiology for GPs: a one-day update', specialty: 'Cardiology', eventType: 'course', startIn: 23, format: 'in_person', city: 'Birmingham', region: 'West Midlands', country: 'uk', society: 'RCGP', priceMin: 95, priceMax: 95, cpdAccredited: true, cpdPoints: 6 },
  { name: 'BTOG Annual Conference 2027', specialty: 'Oncology', eventType: 'conference', startIn: 150, endIn: 152, format: 'in_person', city: 'Belfast', region: 'Northern Ireland', country: 'uk', society: 'BTOG', priceMin: 220, priceMax: 390, cpdAccredited: true, abstractDeadlineIn: 20, abstractOpen: true },
  { name: 'BOPA Annual Symposium', specialty: 'Oncology', eventType: 'conference', startIn: 170, format: 'hybrid', city: 'Nottingham', region: 'East Midlands', country: 'uk', society: 'BOPA', priceMin: 0, cpdAccredited: true, cpdPoints: 4 },
  { name: 'ESTRO Annual Congress 2027', specialty: 'Oncology', eventType: 'conference', isFlagship: true, startIn: 240, endIn: 243, format: 'in_person', city: 'Vienna', region: 'International', country: 'international', society: 'ESTRO', priceMin: 590, priceMax: 1050, currency: 'EUR', cpdAccredited: true, abstractDeadlineIn: 110, abstractOpen: true },
  { name: 'SABCS 2027 — San Antonio Breast Cancer Symposium', specialty: 'Oncology', eventType: 'conference', isFlagship: true, startIn: 330, endIn: 333, format: 'hybrid', city: 'San Antonio', region: 'Texas', country: 'international', society: 'SABCS', priceMin: 675, priceMax: 1120, currency: 'USD', cpdAccredited: true, abstractDeadlineIn: 160, abstractOpen: true },
  { name: 'ESGO State of the Art Conference', specialty: 'Gynaecological Oncology', eventType: 'conference', startIn: 205, endIn: 207, format: 'in_person', city: 'Lisbon', region: 'International', country: 'international', society: 'ESGO', priceMin: 380, priceMax: 690, currency: 'EUR', cpdAccredited: true, abstractDeadlineIn: 50, abstractOpen: true },
  { name: 'SITC Annual Meeting 2027', specialty: 'Oncology', eventType: 'conference', isFlagship: true, startIn: 260, endIn: 263, format: 'hybrid', city: 'National Harbor', region: 'Maryland', country: 'international', society: 'SITC', priceMin: 495, priceMax: 950, currency: 'USD', cpdAccredited: true, abstractDeadlineIn: 130, abstractOpen: true },
  { name: 'Advanced Life Support Provider Course', specialty: 'Emergency Medicine', eventType: 'course', isSoldOut: true, startIn: 14, endIn: 15, format: 'in_person', city: 'Sheffield', region: 'Yorkshire', country: 'uk', society: 'ALSG', priceMin: 395, priceMax: 395, cpdAccredited: true, cpdPoints: 14 },
  { name: 'RCPSG Members Day 2027', specialty: 'General Medicine', eventType: 'conference', startIn: 55, format: 'in_person', city: 'Glasgow', region: 'Scotland', country: 'uk', society: 'RCPSG', priceMin: 60, priceMax: 60, cpdAccredited: true, cpdPoints: 3 },
  { name: 'Histopathology of the Breast: a diagnostic workshop', specialty: 'Pathology', eventType: 'workshop', startIn: 27, format: 'in_person', city: 'Oxford', region: 'South East', country: 'uk', society: 'RCPath', priceMin: 140, priceMax: 140, cpdAccredited: true, cpdPoints: 5 },
  { name: 'RCPsych International Congress 2027', specialty: 'Psychiatry', eventType: 'conference', isFlagship: true, startIn: 310, endIn: 313, format: 'in_person', city: 'Liverpool', region: 'North West', country: 'uk', society: 'RCPsych', priceMin: 310, priceMax: 540, cpdAccredited: true, abstractDeadlineIn: 140, abstractOpen: true },
  { name: 'Edinburgh Surgical Update', specialty: 'General Surgery', eventType: 'conference', startIn: 70, format: 'in_person', city: 'Edinburgh', region: 'Scotland', country: 'uk', society: 'RCSEd', priceMin: 180, priceMax: 180, cpdAccredited: true, cpdPoints: 7 },
  { name: 'Resuscitation Council UK: Immediate Life Support', specialty: 'Emergency Medicine', eventType: 'course', startIn: 8, format: 'in_person', city: 'Cardiff', region: 'Wales', country: 'uk', society: 'Resus Council UK', priceMin: 165, priceMax: 165, cpdAccredited: true, cpdPoints: 4 },
  { name: 'RCPE Consultants Conference', specialty: 'General Medicine', eventType: 'conference', startIn: 95, format: 'in_person', city: 'Edinburgh', region: 'Scotland', country: 'uk', society: 'RCPE', priceMin: 145, priceMax: 145, cpdAccredited: true, cpdPoints: 6 },
  { name: 'Paediatric Emergencies Study Day', specialty: 'Paediatrics', eventType: 'course', startIn: 33, format: 'in_person', city: 'Bristol', region: 'South West', country: 'uk', society: 'RCPCH', priceMin: 110, priceMax: 110, cpdAccredited: true, cpdPoints: 5 },
  { name: 'Ophthalmology Update: Medical Retina', specialty: 'Ophthalmology', eventType: 'conference', startIn: 48, format: 'online', city: null, region: null, country: 'uk', society: 'RCOphth', priceMin: 85, priceMax: 85, cpdAccredited: true, cpdPoints: 4 },
  { name: 'Faculty of Public Health Annual Conference', specialty: 'Public Health', eventType: 'conference', startIn: 120, format: 'in_person', city: 'London', region: 'London', country: 'uk', society: 'FPH', priceMin: 220, priceMax: 220, cpdAccredited: true, abstractDeadlineIn: 30, abstractOpen: true },
  { name: 'Faculty of Occupational Medicine Spring Meeting', specialty: 'Occupational Medicine', eventType: 'conference', startIn: 65, format: 'in_person', city: 'Leeds', region: 'Yorkshire', country: 'uk', society: 'FOM', priceMin: 0 },
  { name: 'Pharmaceutical Medicine Essentials', specialty: 'Pharmaceutical Medicine', eventType: 'course', startIn: 42, format: 'online', city: null, region: null, country: 'uk', society: 'FPM', priceMin: 60, priceMax: 60, cpdAccredited: true, cpdPoints: 3 },
  { name: 'ESC Congress 2027', specialty: 'Cardiology', eventType: 'conference', isFlagship: true, startIn: 225, endIn: 229, format: 'hybrid', city: 'Barcelona', region: 'International', country: 'international', society: 'ESC', priceMin: 550, priceMax: 980, currency: 'EUR', cpdAccredited: true, abstractDeadlineIn: 85, abstractOpen: true },
  { name: 'ACPGBI Annual Meeting', specialty: 'Colorectal Surgery', eventType: 'conference', startIn: 140, format: 'in_person', city: 'Bournemouth', region: 'South West', country: 'uk', society: 'ACPGBI', priceMin: 310, priceMax: 310, cpdAccredited: true, abstractDeadlineIn: 40, abstractOpen: true },
  { name: 'ASGBI International Surgical Congress', specialty: 'Surgery', eventType: 'conference', startIn: 160, endIn: 162, format: 'in_person', city: 'Belfast', region: 'Northern Ireland', country: 'uk', society: 'ASGBI', priceMin: 340, priceMax: 620, cpdAccredited: true, abstractDeadlineIn: 55, abstractOpen: true },
  { name: 'CoSRH Annual Scientific Meeting', specialty: 'Sexual and Reproductive Health', eventType: 'conference', startIn: 80, format: 'in_person', city: 'Brighton', region: 'South East', country: 'uk', society: 'CoSRH', priceMin: 150, priceMax: 150, cpdAccredited: true, cpdPoints: 6 },
  { name: 'FICM Intensive Care State of the Art Meeting', specialty: 'Intensive Care Medicine', eventType: 'conference', startIn: 105, format: 'in_person', city: 'London', region: 'London', country: 'uk', society: 'FICM', priceMin: 265, priceMax: 265, cpdAccredited: true, cpdPoints: 8 },
  { name: 'ARVO Annual Meeting 2027', specialty: 'Ophthalmology', eventType: 'conference', isFlagship: true, startIn: 275, endIn: 279, format: 'hybrid', city: 'Seattle', region: 'Washington', country: 'international', society: 'ARVO', priceMin: 605, priceMax: 1090, currency: 'USD', cpdAccredited: true, abstractDeadlineIn: 120, abstractOpen: true },
  { name: 'International AIDS Conference 2027', specialty: 'HIV Medicine', eventType: 'conference', isFlagship: true, startIn: 300, endIn: 304, format: 'hybrid', city: 'Geneva', region: 'International', country: 'international', society: 'IAS', priceMin: 300, priceMax: 540, currency: 'EUR', cpdAccredited: true, abstractDeadlineIn: 150, abstractOpen: true },
  { name: 'MDDUS Risk Management Workshop', specialty: 'Medico-Legal', eventType: 'workshop', startIn: 17, format: 'online', city: null, region: null, country: 'uk', society: 'MDDUS', priceMin: 0 },
  { name: 'MDU Essentials for New Consultants', specialty: 'Medico-Legal', eventType: 'workshop', startIn: 5, format: 'online', city: null, region: null, country: 'uk', society: 'MDU', priceMin: 0 },
  { name: 'RSM Winter Meeting: Innovations in Digital Health', specialty: 'Digital Health', eventType: 'conference', startIn: 29, format: 'hybrid', city: 'London', region: 'London', country: 'uk', society: 'RSM', priceMin: 75, priceMax: 230, cpdAccredited: true, cpdPoints: 5, abstractDeadlineIn: 10, abstractOpen: true },
  { name: 'Royal College of Surgeons Diploma Revision Course', specialty: 'Exam Preparation', eventType: 'course', startIn: 52, endIn: 53, format: 'in_person', city: 'London', region: 'London', country: 'uk', society: 'RCSEng', priceMin: 480, priceMax: 480, cpdAccredited: true, cpdPoints: 10 },
]

export const FIXTURE_EVENTS: DirectoryEvent[] = SEEDS.map((s, i) => ({
  id: i + 1,
  name: s.name,
  href: `/conferences/${i + 1}`,
  specialty: s.specialty,
  eventType: s.eventType,
  isFlagship: !!s.isFlagship,
  isOnDemand: !!s.isOnDemand,
  isSoldOut: !!s.isSoldOut,
  startDate: inDays(s.startIn),
  endDate: s.endIn != null ? inDays(s.endIn) : null,
  format: s.format,
  city: s.city,
  region: s.region,
  society: s.society,
  priceMin: s.priceMin ?? null,
  priceMax: s.priceMax ?? s.priceMin ?? null,
  currency: s.currency ?? 'GBP',
  cpdAccredited: !!s.cpdAccredited,
  cpdPoints: s.cpdPoints ?? null,
  abstractDeadline: s.abstractDeadlineIn != null ? inDays(s.abstractDeadlineIn) : null,
  abstractDeadlineNote: s.abstractDeadlineNote ?? null,
  abstractOpen: s.abstractOpen ?? s.abstractDeadlineIn != null,
  country: s.country,
  sourceShortName: s.society,
}))

function matches(e: DirectoryEvent, f: DirectoryFilters, skip: keyof DirectoryFilters | null): boolean {
  if (skip !== 'format' && f.format.length && (!e.format || !f.format.includes(e.format))) return false
  if (skip !== 'type' && f.type.length && !f.type.includes(e.eventType)) return false
  if (skip !== 'specialty' && f.specialty.length) {
    const { parent } = canonicalSpecialty(e.specialty)
    if (!f.specialty.includes(parent)) return false
  }
  if (skip !== 'region' && f.region.length && (!e.region || !f.region.includes(e.region))) return false
  if (skip !== 'country' && f.country && e.country !== f.country) return false
  if (skip !== 'society' && f.society.length && (!e.society || !f.society.includes(e.society))) return false
  if (skip !== 'cpd' && f.cpd && !e.cpdAccredited) return false
  if (skip !== 'abstractsOpen' && f.abstractsOpen && !e.abstractOpen) return false

  if (skip !== 'price' && f.price !== 'any') {
    const bucket = classifyPriceBucket(e.priceMin)
    if (f.price === 'free' && bucket !== 'free') return false
    if (f.price === 'under-100' && !(bucket === 'free' || bucket === 'under-100')) return false
    if (f.price === 'under-300' && !(bucket === 'free' || bucket === 'under-100' || bucket === 'under-300')) return false
  }

  if (skip !== 'datePreset' && skip !== 'dateFrom' && skip !== 'dateTo') {
    const { from, to } = f.datePreset ? resolveDatePreset(f.datePreset) : { from: f.dateFrom, to: f.dateTo }
    if (from && (!e.startDate || e.startDate < from)) return false
    if (to && (!e.startDate || e.startDate > to)) return false
  }

  if (skip !== 'q' && f.q.trim()) {
    const needle = f.q.trim().toLowerCase()
    const haystack = `${e.name} ${e.specialty ?? ''} ${e.city ?? ''}`.toLowerCase()
    if (!haystack.includes(needle)) return false
  }

  return true
}

export function queryDirectoryFixture(filters: Partial<DirectoryFilters> = {}): DirectoryPage {
  const f: DirectoryFilters = { ...DEFAULT_FILTERS, ...filters }
  const filtered = FIXTURE_EVENTS.filter((e) => matches(e, f, null))

  const sorted = [...filtered].sort((a, b) => {
    if (f.sort === 'price') {
      if (a.priceMin == null) return 1
      if (b.priceMin == null) return -1
      return a.priceMin - b.priceMin
    }
    if (f.sort === 'newest') return b.id - a.id // fixture has no created_at; id order stands in
    return (a.startDate ?? '9999').localeCompare(b.startDate ?? '9999')
  })

  const pageSize = f.pageSize > 0 ? f.pageSize : DEFAULT_FILTERS.pageSize
  const page = f.page > 0 ? f.page : 1
  const start = (page - 1) * pageSize

  return { rows: sorted.slice(start, start + pageSize), total: sorted.length, page, pageSize }
}

export function queryFacetsFixture(filters: Partial<DirectoryFilters> = {}): DirectoryFacets {
  const f: DirectoryFilters = { ...DEFAULT_FILTERS, ...filters }

  function countBy(key: keyof DirectoryFilters, get: (e: DirectoryEvent) => string[] | string | null): Record<string, number> {
    const pool = FIXTURE_EVENTS.filter((e) => matches(e, f, key))
    const out: Record<string, number> = {}
    for (const e of pool) {
      const v = get(e)
      for (const value of Array.isArray(v) ? v : [v]) {
        if (!value) continue
        out[value] = (out[value] ?? 0) + 1
      }
    }
    return out
  }

  const specialtyPool = FIXTURE_EVENTS.filter((e) => matches(e, f, 'specialty'))
  const specialty: Record<string, number> = {}
  for (const e of specialtyPool) {
    const { parent } = canonicalSpecialty(e.specialty)
    specialty[parent] = (specialty[parent] ?? 0) + 1
  }

  return {
    format: countBy('format', (e) => e.format),
    type: countBy('type', (e) => e.eventType),
    region: countBy('region', (e) => e.region),
    country: countBy('country', (e) => e.country ?? null),
    society: countBy('society', (e) => e.society),
    priceBucket: countBy('price', (e) => classifyPriceBucket(e.priceMin)),
    cpd: countBy('cpd', (e) => (e.cpdAccredited ? 'true' : 'false')),
    specialty,
  }
}
