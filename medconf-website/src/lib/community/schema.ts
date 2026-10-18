// src/lib/community/schema.ts
// zod schemas for community payloads (board §2). One source of truth for the
// add-info dialog, the /submit wizard and the tests. Rules:
//   dates ≥ today (UTC), end ≥ start, abstract_deadline ≤ start,
//   http(s)-only URLs, length caps, ≤ 12 tiers, whitelisted currencies.

import { z } from 'zod'
import { normalizeUrl } from './normalize-url'
import { FACT_FIELD_LIST } from './types'
import { SPECIALTY_PARENTS } from '../taxonomy/specialties'

export const FACT_FIELDS = FACT_FIELD_LIST

export const CURRENCIES = ['GBP', 'USD', 'EUR', 'AUD', 'CAD', 'INR', 'CHF', 'HKD', 'SGD'] as const
export type Currency = (typeof CURRENCIES)[number]

export const FEE_LABELS = ['Standard', 'Member', 'Non-member', 'Trainee / Student', 'Early bird', 'Free'] as const

export const UK_NATIONS = ['England', 'Scotland', 'Wales', 'Northern Ireland'] as const

export const MAX_TIERS = 12
export const LIMITS = {
  name: 200,
  description: 2000,
  note: 1000,
  short: 200,
  url: 2000,
  tierLabel: 40,
  maxPrice: 100000,
} as const

/** Today as a UTC YYYY-MM-DD string (matches how dates are stored). */
export function todayUtc(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10)
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function isRealDate(s: string): boolean {
  if (!ISO_DATE.test(s)) return false
  const d = new Date(`${s}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s
}

const dateString = z.string().refine(isRealDate, 'Enter a valid date')
const futureDate = dateString.refine((s) => s >= todayUtc(), 'Date must be today or later')

const timeString = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, 'Use HH:MM (24-hour)')

/** http(s)-only; stored in normalised form. */
const urlString = z
  .string()
  .max(LIMITS.url, 'Link is too long')
  .refine((s) => normalizeUrl(s) !== null, 'Enter a full link starting with http:// or https://')
  .transform((s) => normalizeUrl(s) as string)

const trimmed = (max: number, label = 'Text') =>
  z.string().trim().min(1, `${label} is required`).max(max, `Keep this under ${max} characters`)

/* ---------------------------------------------------------------- fees */

export const feeTierSchema = z
  .object({
    label: trimmed(LIMITS.tierLabel, 'Label'),
    price: z.number({ error: 'Enter a price' }).min(0, 'Price cannot be negative').max(LIMITS.maxPrice, 'Price looks too high'),
    is_early_bird: z.boolean(),
    early_bird_deadline: dateString.optional(),
  })
  .superRefine((t, ctx) => {
    if (t.is_early_bird && t.early_bird_deadline && t.early_bird_deadline < todayUtc()) {
      ctx.addIssue({ code: 'custom', path: ['early_bird_deadline'], message: 'Deadline must be today or later' })
    }
  })

export const feesSchema = z.object({
  currency: z.enum(CURRENCIES, { error: 'Choose a currency' }),
  from_price: z.number().min(0).max(LIMITS.maxPrice).optional(),
  tiers: z.array(feeTierSchema).max(MAX_TIERS, `Add at most ${MAX_TIERS} fee tiers`),
  notes: z.string().trim().max(300, 'Keep notes under 300 characters').optional(),
})

/* ------------------------------------------------------------ add_info */

/** conferences.cpd_points is an INTEGER column; the overlay enforces the same range. */
const cpdPoints = z
  .number({ error: 'Whole number of CPD points, up to 500' })
  .int('Whole number of CPD points, up to 500')
  .min(0, 'Points cannot be negative')
  .max(500, 'Whole number of CPD points, up to 500')

function addInfoFieldsObject() {
  return z.strictObject({
    start_date: futureDate,
    end_date: futureDate,
    start_time: timeString,
    venue_name: trimmed(LIMITS.short, 'Venue'),
    city: trimmed(100, 'City'),
    region: trimmed(100, 'Region'),
    event_format: z.enum(['in_person', 'online', 'hybrid']),
    abstract_deadline: futureDate,
    abstract_open: z.boolean(),
    abstract_deadline_note: trimmed(LIMITS.short, 'Note'),
    cpd_accredited: z.boolean(),
    cpd_points: cpdPoints,
    organiser_url: urlString,
    booking_url: urlString,
    description: trimmed(LIMITS.description, 'Description'),
    note: trimmed(LIMITS.note, 'Note'),
  })
}

export interface AddInfoContext {
  /** The listing's existing start date, so a new deadline is checked against it. */
  startDate?: string | null
  endDate?: string | null
}

/**
 * add_info payload schema. `ctx` lets cross-field rules see the scraped dates
 * of the listing being enriched (e.g. an abstract deadline must not fall after
 * the event starts).
 */
export function makeAddInfoSchema(ctx: AddInfoContext = {}) {
  return z
    .object({
      fields: addInfoFieldsObject().partial(),
      fees: feesSchema.optional(),
      note: z.string().trim().max(LIMITS.note, `Keep this under ${LIMITS.note} characters`).optional(),
      evidence_url: urlString.optional(),
    })
    .superRefine((p, c) => {
      const f = p.fields
      const start = f.start_date ?? ctx.startDate ?? null
      const end = f.end_date ?? ctx.endDate ?? null
      if (start && end && end < start) {
        c.addIssue({ code: 'custom', path: ['fields', 'end_date'], message: 'End date cannot be before the start date' })
      }
      if (f.abstract_deadline && start && f.abstract_deadline > start) {
        c.addIssue({
          code: 'custom',
          path: ['fields', 'abstract_deadline'],
          message: 'Abstract deadline must be on or before the event start',
        })
      }
      if (f.cpd_points !== undefined && f.cpd_accredited === false) {
        c.addIssue({ code: 'custom', path: ['fields', 'cpd_points'], message: 'Points need CPD accreditation to be ticked' })
      }
      const hasFields = Object.keys(f).length > 0
      const hasFees = !!p.fees && (p.fees.tiers.length > 0 || p.fees.from_price !== undefined)
      if (!hasFields && !hasFees) {
        c.addIssue({ code: 'custom', path: [], message: 'Add at least one piece of information before sending' })
      }
    })
}

export const addInfoPayloadSchema = makeAddInfoSchema()

/* ----------------------------------------------------------- new_event */

const specialtyLabels = SPECIALTY_PARENTS.map((p) => p.label) as [string, ...string[]]

export const newEventPayloadSchema = z
  .object({
    conference_name: trimmed(LIMITS.name, 'Event name'),
    event_type: z.enum(['conference', 'workshop', 'course']),
    event_format: z.enum(['in_person', 'online', 'hybrid']),
    is_flagship: z.boolean().optional(),
    start_date: futureDate,
    end_date: futureDate.optional(),
    start_time: timeString.optional(),
    country: trimmed(100, 'Country'),
    region: z.string().trim().max(100).optional(),
    city: z.string().trim().max(100).optional(),
    venue_name: z.string().trim().max(LIMITS.short).optional(),
    specialty: z.enum(specialtyLabels, { error: 'Choose a specialty' }),
    description: z.string().trim().max(LIMITS.description, `Keep this under ${LIMITS.description} characters`).optional(),
    organiser_url: urlString,
    booking_url: urlString.optional(),
    cpd_accredited: z.boolean(),
    cpd_points: cpdPoints.optional(),
    abstract_open: z.boolean(),
    abstract_deadline: futureDate.optional(),
    abstract_deadline_note: z.string().trim().max(LIMITS.short).optional(),
    fees: feesSchema.optional(),
    note: z.string().trim().max(LIMITS.note).optional(),
    evidence_url: urlString.optional(),
  })
  .superRefine((p, ctx) => {
    if (p.end_date && p.end_date < p.start_date) {
      ctx.addIssue({ code: 'custom', path: ['end_date'], message: 'End date cannot be before the start date' })
    }
    if (p.abstract_deadline && p.abstract_deadline > p.start_date) {
      ctx.addIssue({
        code: 'custom',
        path: ['abstract_deadline'],
        message: 'Abstract deadline must be on or before the event start',
      })
    }
    if (p.cpd_points !== undefined && !p.cpd_accredited) {
      ctx.addIssue({ code: 'custom', path: ['cpd_points'], message: 'Points need CPD accreditation to be ticked' })
    }
  })

export type AddInfoInput = z.input<typeof addInfoPayloadSchema>
export type AddInfoOutput = z.output<typeof addInfoPayloadSchema>
export type NewEventOutput = z.output<typeof newEventPayloadSchema>
export type FeesOutput = z.output<typeof feesSchema>
