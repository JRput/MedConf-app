// Pure helpers for the /submit form: values <-> payload, validation, region
// mapping, duplicate flagging, section status. Kept free of React so they can
// be unit-tested in the node vitest environment.

import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'
import { newEventPayloadSchema, FEE_LABELS, UK_NATIONS, LIMITS } from '@/lib/community/schema'
import { sameDomain, normalizeUrl } from '@/lib/community/normalize-url'
import {
  emptyFeesDraft,
  feesDraftToRaw,
  isFeesDraftEmpty,
  newTierDraft,
  validateFeesDraft,
  type FeesDraft,
} from '@/lib/community/fees-draft'
import type { NewEventPayload } from '@/lib/community/types'

export const UK = 'United Kingdom'
export const OTHER_COUNTRY = '__other__'

/** United Kingdom first, then common destinations, then "Other" (free text). */
export const COMMON_COUNTRIES = [
  UK,
  'Ireland',
  'United States',
  'Canada',
  'Australia',
  'Germany',
  'France',
  'Netherlands',
  'Switzerland',
  'Spain',
  'Italy',
  'Belgium',
  'Sweden',
  'Denmark',
  'Singapore',
  'Hong Kong',
  'India',
  'United Arab Emirates',
] as const

export interface SubmitValues {
  conference_name: string
  organiser_url: string
  event_type: '' | 'conference' | 'workshop' | 'course'
  event_format: '' | 'in_person' | 'online' | 'hybrid'
  is_flagship: boolean
  start_date: string
  end_date: string
  start_time: string
  country: string // one of COMMON_COUNTRIES or OTHER_COUNTRY
  country_other: string
  uk_nation: string
  city: string
  venue_name: string
  specialty_slug: string
  cpd_accredited: boolean
  cpd_points: string
  abstract_open: boolean
  abstract_deadline: string
  abstract_deadline_note: string
  description: string
  booking_url: string
  evidence_url: string
  note: string
  consent: boolean
}

export const EMPTY_VALUES: SubmitValues = {
  conference_name: '',
  organiser_url: '',
  event_type: '',
  event_format: '',
  is_flagship: false,
  start_date: '',
  end_date: '',
  start_time: '',
  country: '',
  country_other: '',
  uk_nation: '',
  city: '',
  venue_name: '',
  specialty_slug: '',
  cpd_accredited: false,
  cpd_points: '',
  abstract_open: false,
  abstract_deadline: '',
  abstract_deadline_note: '',
  description: '',
  booking_url: '',
  evidence_url: '',
  note: '',
  consent: false,
}

export const REQUIRED_KEYS = [
  'conference_name',
  'organiser_url',
  'event_type',
  'event_format',
  'start_date',
  'country',
  'specialty',
  'consent',
] as const

export type SectionId = 'basics' | 'when' | 'where' | 'specialty' | 'fees' | 'abstracts' | 'description' | 'links'

export const SECTION_ORDER: { id: SectionId; label: string }[] = [
  { id: 'basics', label: 'Basics' },
  { id: 'when', label: 'When' },
  { id: 'where', label: 'Where' },
  { id: 'specialty', label: 'Specialty' },
  { id: 'fees', label: 'Fees' },
  { id: 'abstracts', label: 'Abstracts & CPD' },
  { id: 'description', label: 'Description' },
  { id: 'links', label: 'Links & evidence' },
]

/** Which section owns each field key (for auto-opening on error). */
export const KEY_SECTION: Record<string, SectionId> = {
  conference_name: 'basics',
  organiser_url: 'basics',
  event_type: 'basics',
  event_format: 'basics',
  is_flagship: 'basics',
  start_date: 'when',
  end_date: 'when',
  start_time: 'when',
  country: 'where',
  region: 'where',
  city: 'where',
  venue_name: 'where',
  specialty: 'specialty',
  fees: 'fees',
  cpd_accredited: 'abstracts',
  cpd_points: 'abstracts',
  abstract_open: 'abstracts',
  abstract_deadline: 'abstracts',
  abstract_deadline_note: 'abstracts',
  description: 'description',
  booking_url: 'links',
  evidence_url: 'links',
  note: 'links',
}

export function specialtyLabel(slug: string): string {
  return SPECIALTY_PARENTS.find((p) => p.slug === slug)?.label ?? ''
}

export function specialtySlug(label: string): string {
  return SPECIALTY_PARENTS.find((p) => p.label === label)?.slug ?? ''
}

export function countryName(v: Pick<SubmitValues, 'country' | 'country_other'>): string {
  return v.country === OTHER_COUNTRY ? v.country_other.trim() : v.country.trim()
}

/** UK -> the chosen nation; anywhere else -> the country name (board §1.2). */
export function regionFor(v: Pick<SubmitValues, 'country' | 'country_other' | 'uk_nation'>): string | undefined {
  const country = countryName(v)
  if (!country) return undefined
  if (country === UK) return v.uk_nation.trim() || undefined
  return country
}

const blank = (s: string) => (s.trim() === '' ? undefined : s.trim())

/** Raw (pre-zod) payload. Dependent fields are dropped when their parent toggle is off. */
export function buildRawPayload(v: SubmitValues, fees: FeesDraft): Record<string, unknown> {
  const country = countryName(v)
  const online = v.event_format === 'online'
  const raw: Record<string, unknown> = {
    conference_name: v.conference_name,
    event_type: v.event_type || undefined,
    event_format: v.event_format || undefined,
    is_flagship: v.is_flagship || undefined,
    start_date: blank(v.start_date),
    end_date: blank(v.end_date),
    start_time: blank(v.start_time),
    country,
    region: regionFor(v),
    city: blank(v.city),
    venue_name: online ? undefined : blank(v.venue_name),
    specialty: specialtyLabel(v.specialty_slug) || undefined,
    description: blank(v.description),
    organiser_url: v.organiser_url,
    booking_url: blank(v.booking_url),
    cpd_accredited: v.cpd_accredited,
    cpd_points: v.cpd_accredited && v.cpd_points.trim() !== '' ? Number(v.cpd_points) : undefined,
    abstract_open: v.abstract_open,
    abstract_deadline: v.abstract_open ? blank(v.abstract_deadline) : undefined,
    abstract_deadline_note: v.abstract_open ? blank(v.abstract_deadline_note) : undefined,
    fees: isFeesDraftEmpty(fees) ? undefined : feesDraftToRaw(fees),
    note: blank(v.note),
    evidence_url: blank(v.evidence_url),
  }
  for (const k of Object.keys(raw)) if (raw[k] === undefined) delete raw[k]
  return raw
}

export interface SubmitValidation {
  errors: Record<string, string>
  feesInvalid: boolean
  payload: NewEventPayload | null
}

/** Zod-validate a form state. Errors are keyed by the first path segment; consent is checked here. */
export function validateSubmit(v: SubmitValues, fees: FeesDraft): SubmitValidation {
  const errors: Record<string, string> = {}
  let feesInvalid = false
  const raw = buildRawPayload(v, fees)
  const res = newEventPayloadSchema.safeParse(raw)
  if (!res.success) {
    for (const issue of res.error.issues) {
      const key = String(issue.path[0] ?? '')
      if (!key) continue
      if (key === 'fees') {
        feesInvalid = true
        continue
      }
      if (!errors[key]) errors[key] = friendly(key, issue.message, raw)
    }
  }
  if (!v.event_type) errors.event_type = 'Choose what kind of event this is'
  if (!v.event_format) errors.event_format = 'Choose how it is delivered'
  if (!v.specialty_slug) errors.specialty = 'Choose the closest specialty'
  if (v.country === OTHER_COUNTRY && !v.country_other.trim()) errors.country = 'Type the country name'
  if (!v.consent) errors.consent = 'Please confirm before sending'
  if (feesInvalid || !isFeesDraftEmpty(fees)) {
    if (!validateFeesDraft(fees).payload) feesInvalid = true
  }
  const ok = Object.keys(errors).length === 0 && !feesInvalid && res.success
  return { errors, feesInvalid, payload: ok ? (res.data as NewEventPayload) : null }
}

function friendly(key: string, message: string, raw: Record<string, unknown>): string {
  if (/received undefined|expected string|required/i.test(message) || message === 'Invalid input') {
    if (key === 'start_date') return 'Enter the start date'
    if (key === 'organiser_url') return 'Paste the organiser page link, starting with https://'
    if (key === 'conference_name') return 'Enter the event name'
    if (key === 'country') return 'Choose a country'
  }
  if (key === 'organiser_url' && raw.organiser_url === '') return 'Paste the organiser page link, starting with https://'
  if (key === 'start_date' && /today or later/i.test(message)) return 'Date must be today or later. Past events are not listed.'
  return message
}

/* ---------------------------------------------------------- completeness */

export interface SectionStatus {
  id: SectionId
  label: string
  required: number
  done: number
  hasContent: boolean
  hasError: boolean
}

export function sectionStatuses(v: SubmitValues, fees: FeesDraft, errors: Record<string, string>, showErrors: (k: string) => boolean): SectionStatus[] {
  const req = (cond: boolean) => (cond ? 1 : 0)
  const errIn = (id: SectionId) =>
    Object.keys(errors).some((k) => KEY_SECTION[k] === id && showErrors(k)) 
  const mk = (id: SectionId, required: number, done: number, hasContent: boolean): SectionStatus => ({
    id,
    label: SECTION_ORDER.find((s) => s.id === id)!.label,
    required,
    done,
    hasContent,
    hasError: errIn(id),
  })
  const urlOk = normalizeUrl(v.organiser_url) !== null
  return [
    mk('basics', 4, req(!!v.conference_name.trim()) + req(urlOk) + req(!!v.event_type) + req(!!v.event_format), true),
    mk('when', 1, req(!!v.start_date), !!(v.start_date || v.end_date || v.start_time)),
    mk('where', 1, req(!!countryName(v)), !!(countryName(v) || v.city || v.venue_name)),
    mk('specialty', 1, req(!!v.specialty_slug), !!v.specialty_slug),
    mk('fees', 0, 0, !isFeesDraftEmpty(fees)),
    mk('abstracts', 0, 0, v.cpd_accredited || v.abstract_open),
    mk('description', 0, 0, !!v.description.trim()),
    mk('links', 1, req(v.consent), !!(v.booking_url || v.evidence_url || v.note || v.consent)),
  ]
}

/** Required fields not yet satisfied, for the summary card. */
export function missingRequired(v: SubmitValues): string[] {
  const out: string[] = []
  if (!v.conference_name.trim()) out.push('Event name')
  if (normalizeUrl(v.organiser_url) === null) out.push('Organiser link')
  if (!v.event_type) out.push('Event type')
  if (!v.event_format) out.push('Format')
  if (!v.start_date) out.push('Start date')
  if (!countryName(v)) out.push('Country')
  if (!v.specialty_slug) out.push('Specialty')
  if (!v.consent) out.push('Consent')
  return out
}

/* ------------------------------------------------------------ duplicates */

export interface DirectoryMatch {
  id: number
  name: string
  startDate: string | null
  organiserUrl: string | null
}

export interface FlaggedMatch extends DirectoryMatch {
  sameSite: boolean
}

/** Normalise API rows (camelCase view model, or raw snake_case) into matches. */
export function toMatches(rows: unknown): DirectoryMatch[] {
  if (!Array.isArray(rows)) return []
  const out: DirectoryMatch[] = []
  for (const r of rows as Record<string, unknown>[]) {
    const id = Number(r.id)
    const name = (r.name ?? r.conference_name) as string | undefined
    if (!Number.isFinite(id) || !name) continue
    out.push({
      id,
      name,
      startDate: ((r.startDate ?? r.start_date) as string | null | undefined) ?? null,
      organiserUrl: ((r.organiserUrl ?? r.organiser_url ?? r.source_url) as string | null | undefined) ?? null,
    })
  }
  return out
}

/** Flag matches that share the typed organiser's domain; those sort first. */
export function flagDuplicates(matches: DirectoryMatch[], organiserUrl: string): FlaggedMatch[] {
  const flagged = matches.map((m) => ({ ...m, sameSite: sameDomain(m.organiserUrl, organiserUrl) }))
  return flagged.sort((a, b) => Number(b.sameSite) - Number(a.sameSite))
}

export function shouldCheckDuplicates(name: string, organiserUrl: string): boolean {
  return name.trim().length >= 4 || normalizeUrl(organiserUrl) !== null
}

/** Query string for the check: the name when long enough, otherwise the URL host. */
export function duplicateQuery(name: string, organiserUrl: string): string | null {
  if (name.trim().length >= 4) return name.trim()
  const n = normalizeUrl(organiserUrl)
  return n ? new URL(n).hostname.replace(/^www\./, '') : null
}

/* -------------------------------------------------------------- resubmit */

/** Reverse of buildRawPayload for prefilling a needs_info contribution. */
export function payloadToValues(p: Partial<NewEventPayload>): { values: SubmitValues; fees: FeesDraft } {
  const country = p.country ?? ''
  const known = (COMMON_COUNTRIES as readonly string[]).includes(country)
  const values: SubmitValues = {
    ...EMPTY_VALUES,
    conference_name: p.conference_name ?? '',
    organiser_url: p.organiser_url ?? '',
    event_type: p.event_type ?? '',
    event_format: p.event_format ?? '',
    is_flagship: !!p.is_flagship,
    start_date: p.start_date ?? '',
    end_date: p.end_date ?? '',
    start_time: p.start_time ?? '',
    country: country ? (known ? country : OTHER_COUNTRY) : '',
    country_other: country && !known ? country : '',
    uk_nation: country === UK && (UK_NATIONS as readonly string[]).includes(p.region ?? '') ? (p.region as string) : '',
    city: p.city ?? '',
    venue_name: p.venue_name ?? '',
    specialty_slug: specialtySlug(p.specialty ?? ''),
    cpd_accredited: !!p.cpd_accredited,
    cpd_points: p.cpd_points !== undefined ? String(p.cpd_points) : '',
    abstract_open: !!p.abstract_open,
    abstract_deadline: p.abstract_deadline ?? '',
    abstract_deadline_note: p.abstract_deadline_note ?? '',
    description: p.description ?? '',
    booking_url: p.booking_url ?? '',
    evidence_url: p.evidence_url ?? '',
    note: p.note ?? '',
    consent: false, // always re-confirm on resubmit
  }
  const fees = emptyFeesDraft(p.fees?.currency ?? 'GBP')
  if (p.fees) {
    fees.from_price = p.fees.from_price !== undefined ? String(p.fees.from_price) : ''
    fees.tiers = p.fees.tiers.map((t) => {
      const d = newTierDraft(t.label)
      d.custom = !(FEE_LABELS as readonly string[]).includes(t.label)
      d.price = String(t.price)
      d.is_early_bird = t.is_early_bird
      d.early_bird_deadline = t.early_bird_deadline ?? ''
      return d
    })
  }
  return { values, fees }
}

export const DESCRIPTION_MAX = LIMITS.description
