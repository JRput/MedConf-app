// src/lib/community/moderation.ts
// Pure helpers for the moderation UI (board §1.5). No React, no I/O, so every
// rule here is unit-tested in src/lib/__tests__/community-moderation.test.ts.

import { normalizeUrl, sameDomain } from './normalize-url'
import { FEE_LABELS } from './schema'
import { newTierDraft, type FeesDraft } from './fees-draft'
import type { Contribution, ContributionStatus, EnrichmentStatus, FeesPayload, FeeTierPayload } from './types'

type Payload = Record<string, unknown>
/** Enrichment as stored (jsonb). Loose on purpose: the job also writes internal keys such as `_error`. */
export type EnrichmentInput = Record<string, unknown> | null | undefined
interface EnrichmentEntry {
  value: unknown
  method: string
  agrees: boolean | null
}

// ---------------------------------------------------------------- field meta

export type FieldKind = 'text' | 'date' | 'time' | 'select' | 'boolean' | 'number' | 'textarea' | 'url'

export interface FieldMeta {
  label: string
  kind: FieldKind
  options?: { value: string; label: string }[]
}

const FORMAT_OPTIONS = [
  { value: 'in_person', label: 'In person' },
  { value: 'online', label: 'Online' },
  { value: 'hybrid', label: 'Hybrid' },
]
const TYPE_OPTIONS = [
  { value: 'conference', label: 'Conference' },
  { value: 'workshop', label: 'Workshop' },
  { value: 'course', label: 'Course' },
]

export const FIELD_META: Record<string, FieldMeta> = {
  conference_name: { label: 'conference_name', kind: 'text' },
  event_type: { label: 'event_type', kind: 'select', options: TYPE_OPTIONS },
  event_format: { label: 'event_format', kind: 'select', options: FORMAT_OPTIONS },
  is_flagship: { label: 'is_flagship', kind: 'boolean' },
  specialty: { label: 'specialty', kind: 'text' },
  start_date: { label: 'start_date', kind: 'date' },
  end_date: { label: 'end_date', kind: 'date' },
  start_time: { label: 'start_time', kind: 'time' },
  country: { label: 'country', kind: 'text' },
  region: { label: 'region', kind: 'text' },
  city: { label: 'city', kind: 'text' },
  venue_name: { label: 'venue_name', kind: 'text' },
  organiser_url: { label: 'organiser_url', kind: 'url' },
  booking_url: { label: 'booking_url', kind: 'url' },
  cpd_accredited: { label: 'cpd_accredited', kind: 'boolean' },
  cpd_points: { label: 'cpd_points', kind: 'number' },
  abstract_open: { label: 'abstract_open', kind: 'boolean' },
  abstract_deadline: { label: 'abstract_deadline', kind: 'date' },
  abstract_deadline_note: { label: 'abstract_deadline_note', kind: 'text' },
  description: { label: 'description', kind: 'textarea' },
  note: { label: 'note', kind: 'textarea' },
}

/** Review order. Fields not listed sort after these, alphabetically. */
export const FIELD_ORDER = Object.keys(FIELD_META)

/** Payload keys that are not "fields" (reviewed elsewhere or never published). */
const NON_FIELD_KEYS = new Set(['fees', 'fields', 'evidence_url'])

export function fieldMeta(field: string): FieldMeta {
  return FIELD_META[field] ?? { label: field, kind: 'text' }
}

// ---------------------------------------------------------------- basics

export function isBlank(v: unknown): boolean {
  return v === undefined || v === null || (typeof v === 'string' && v.trim() === '')
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** The user's flat field map: `payload.fields` for add_info, the payload itself for new_event. */
export function userFields(payload: unknown): Payload {
  if (!isRecord(payload)) return {}
  if (isRecord(payload.fields)) return { ...payload.fields }
  const out: Payload = {}
  for (const [k, v] of Object.entries(payload)) {
    // `note` on a new event is the private message to moderators, never published.
    if (!NON_FIELD_KEYS.has(k) && k !== 'note') out[k] = v
  }
  return out
}

export function isAddInfo(payload: unknown): boolean {
  return isRecord(payload) && isRecord(payload.fields)
}

function userFees(payload: unknown): FeesPayload | undefined {
  if (!isRecord(payload) || !isRecord(payload.fees)) return undefined
  const f = payload.fees as unknown as FeesPayload
  return Array.isArray(f.tiers) ? f : undefined
}

// ---------------------------------------------------------------- enrichment

export interface FoundField {
  value: unknown
  method: string
  agrees: boolean | null
}

/**
 * Enrichment as one flat field map. The job stores `abstract_status` as a
 * dict (abstract_open / abstract_deadline / abstract_deadline_note); expand it
 * so each piece lines up with a payload field. `pricing` stays under its own
 * key (see foundTiers). Internal keys (`_error`) are dropped.
 */
export function flattenEnrichment(
  enrichment: EnrichmentInput,
  user?: Payload
): Record<string, FoundField> {
  const out: Record<string, FoundField> = {}
  if (!enrichment) return out
  for (const [key, entry] of Object.entries(enrichment)) {
    if (key.startsWith('_') || !isRecord(entry)) continue
    const e = entry as unknown as EnrichmentEntry
    if (key === 'abstract_status' && isRecord(e.value)) {
      for (const [sub, subValue] of Object.entries(e.value)) {
        if (subValue === null || subValue === undefined) continue
        let agrees: boolean | null = null
        if (user && !isBlank(user[sub])) agrees = String(user[sub]).slice(0, 10) === String(subValue).slice(0, 10) || user[sub] === subValue
        else if (!user) agrees = e.agrees
        out[sub] = { value: subValue, method: e.method, agrees }
      }
      continue
    }
    out[key] = { value: e.value, method: e.method, agrees: e.agrees }
  }
  return out
}

/** Fee tiers the organiser site showed, mapped to the payload tier shape. */
export function foundTiers(enrichment: EnrichmentInput): {
  currency: string
  tiers: FeeTierPayload[]
  method: string
  agrees: boolean | null
} | null {
  const e = enrichment?.pricing as EnrichmentEntry | undefined
  if (!isRecord(e) || !Array.isArray(e.value) || e.value.length === 0) return null
  const tiers: FeeTierPayload[] = []
  let currency = 'GBP'
  for (const raw of e.value as unknown[]) {
    if (!isRecord(raw)) continue
    const price = Number(raw.price_gbp ?? raw.price)
    if (!Number.isFinite(price)) continue
    if (typeof raw.currency === 'string' && raw.currency) currency = raw.currency
    const tier: FeeTierPayload = {
      label: String(raw.tier_label ?? raw.label ?? 'Standard').slice(0, 40),
      price,
      is_early_bird: raw.is_early_bird === true,
    }
    if (typeof raw.early_bird_deadline === 'string' && raw.early_bird_deadline) tier.early_bird_deadline = raw.early_bird_deadline
    tiers.push(tier)
  }
  if (tiers.length === 0) return null
  return { currency, tiers: tiers.slice(0, 12), method: e.method, agrees: e.agrees }
}

/** Fields where the organiser site contradicts the submitter (`agrees === false`). `fees` stands for pricing. */
export function disagreementFields(enrichment: EnrichmentInput, user?: Payload): string[] {
  const flat = flattenEnrichment(enrichment, user)
  const out = Object.entries(flat)
    .filter(([key, f]) => key !== 'pricing' && f.agrees === false)
    .map(([key]) => key)
  if (flat.pricing?.agrees === false) out.push('fees')
  return out.sort((a, b) => orderIndex(a) - orderIndex(b))
}

function orderIndex(field: string): number {
  const i = FIELD_ORDER.indexOf(field)
  return i === -1 ? FIELD_ORDER.length : i
}

// ---------------------------------------------------------------- final payload

export type EditMap = Record<string, unknown>

export interface FieldRow {
  field: string
  user: unknown
  found: FoundField | null
  /** The value that will be sent. */
  final: unknown
  /** True when `final` came from the organiser site because the submitter left it empty. */
  fromEnrichment: boolean
  disagrees: boolean
}

function coerce(field: string, v: unknown): unknown {
  if (isBlank(v)) return undefined
  const kind = fieldMeta(field).kind
  if (kind === 'number') {
    const n = typeof v === 'number' ? v : Number(String(v).trim())
    return Number.isFinite(n) ? n : undefined
  }
  if (kind === 'boolean') return v === true || v === 'true'
  return typeof v === 'string' ? v.trim() : v
}

/**
 * Which fields get a review row: everything the submitter typed plus
 * everything the organiser site returned (fees live in the tier table).
 */
export function reviewFieldNames(user: Payload, found: Record<string, FoundField>): string[] {
  const names = new Set<string>()
  for (const [k, v] of Object.entries(user)) if (!isBlank(v)) names.add(k)
  for (const k of Object.keys(found)) if (k !== 'pricing') names.add(k)
  return [...names].sort((a, b) => orderIndex(a) - orderIndex(b) || a.localeCompare(b))
}

/**
 * Compute every review row. Final = moderator edit, else the user's value,
 * else (new events only) the organiser-site value flagged `fromEnrichment`.
 * For add_info the organiser value is never auto-applied: a community fact
 * should only exist for something a member actually asserted.
 */
export function buildFieldRows(
  payload: unknown,
  enrichment: EnrichmentInput,
  edits: EditMap = {}
): FieldRow[] {
  const user = userFields(payload)
  const found = flattenEnrichment(enrichment, user)
  const addInfo = isAddInfo(payload)
  return reviewFieldNames(user, found).map((field) => {
    const f = found[field] ?? null
    const u = isBlank(user[field]) ? undefined : user[field]
    let final: unknown
    let fromEnrichment = false
    if (Object.prototype.hasOwnProperty.call(edits, field)) {
      final = coerce(field, edits[field])
    } else if (u !== undefined) {
      final = coerce(field, u)
    } else if (!addInfo && f && !isBlank(f.value)) {
      final = coerce(field, f.value)
      fromEnrichment = final !== undefined
    }
    // An edited value that equals the found value is still a conscious choice.
    return { field, user: u, found: f, final, fromEnrichment, disagrees: f?.agrees === false }
  })
}

/** URLs the enrichment safety check rejected (`_rejected_urls`: strings or `{url}` objects). Normalised. */
export function rejectedUrls(enrichment: EnrichmentInput): string[] {
  const raw = enrichment?._rejected_urls
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  for (const r of raw) {
    const u = typeof r === 'string' ? r : isRecord(r) && typeof r.url === 'string' ? r.url : null
    if (!u) continue
    const n = normalizeUrl(u) ?? u.trim()
    if (n && !out.includes(n)) out.push(n)
  }
  return out
}

export interface FinalResult {
  /** Payload to send as p_final (same shape as the submission). */
  final: Payload
  /** Fields whose final value came from the organiser site, not the submitter. */
  prefilled: string[]
  /** URL fields removed because the safety check rejected the link. */
  stripped: string[]
}

/**
 * Build the p_final payload for approve/merge.
 * - add_info: `{ fields: {...}, fees?, note?, evidence_url? }`
 * - new_event: flat payload with `fees`
 * URLs are re-normalised. `edits.fees` (a FeesPayload or null to clear)
 * overrides the fee table; with no user fees, found tiers prefill a new event.
 */
export function buildFinalPayload(payload: unknown, enrichment: EnrichmentInput, edits: EditMap = {}): FinalResult {
  const rows = buildFieldRows(payload, enrichment, edits)
  const prefilled: string[] = []
  const stripped: string[] = []
  const rejected = new Set(rejectedUrls(enrichment))
  const flat: Payload = {}
  for (const r of rows) {
    if (r.final === undefined || r.final === '') continue
    let v = r.final
    if (fieldMeta(r.field).kind === 'url' && typeof v === 'string') {
      v = normalizeUrl(v) ?? v
      // Never publish a link the safety check rejected.
      if (rejected.has(v as string)) {
        stripped.push(r.field)
        continue
      }
    }
    flat[r.field] = v
    if (r.fromEnrichment) prefilled.push(r.field)
  }

  // fees
  let fees: FeesPayload | undefined
  if (Object.prototype.hasOwnProperty.call(edits, 'fees')) {
    fees = (edits.fees as FeesPayload | null | undefined) ?? undefined
  } else {
    fees = userFees(payload)
    if (!fees && !isAddInfo(payload)) {
      const ft = foundTiers(enrichment)
      if (ft) {
        fees = { currency: ft.currency, tiers: ft.tiers }
        prefilled.push('fees')
      }
    }
  }
  const hasFees = !!fees && ((fees.tiers?.length ?? 0) > 0 || fees.from_price != null)

  const base = isRecord(payload) ? payload : {}
  const extras: Payload = {}
  if (!isBlank(base.evidence_url) && !rejected.has(normalizeUrl(String(base.evidence_url)) ?? String(base.evidence_url))) extras.evidence_url = base.evidence_url

  if (isAddInfo(payload)) {
    const out: Payload = { fields: flat }
    if (hasFees) out.fees = fees
    if (!isBlank(base.note)) out.note = base.note
    return { final: { ...out, ...extras }, prefilled, stripped }
  }
  const out: Payload = { ...flat }
  if (hasFees) out.fees = fees
  return { final: { ...out, ...extras }, prefilled, stripped }
}

/** Problems that would make the RPC insert fail or list a broken event. Empty = fine. */
export function finalProblems(payload: unknown, final: Payload): string[] {
  const problems: string[] = []
  const flat = isAddInfo(payload) ? (final.fields as Payload) ?? {} : final
  if (isAddInfo(payload)) {
    if (Object.keys(flat).length === 0 && !final.fees) problems.push('Nothing to publish: every field is empty.')
    return problems
  }
  if (isBlank(flat.conference_name)) problems.push('Event name is required.')
  if (typeof flat.start_date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(flat.start_date)) problems.push('Start date is required.')
  if (typeof flat.end_date === 'string' && typeof flat.start_date === 'string' && flat.end_date < flat.start_date)
    problems.push('End date is before the start date.')
  if (!normalizeUrl(typeof flat.organiser_url === 'string' ? flat.organiser_url : null)) problems.push('A valid organiser URL (http or https) is required.')
  return problems
}

/** Payload fees -> editable draft for the fee editor. Labels outside the standard list become custom. */
export function feesPayloadToDraft(fees: FeesPayload | undefined | null, fallbackCurrency = 'GBP'): FeesDraft {
  const labels = FEE_LABELS as readonly string[]
  return {
    currency: fees?.currency ?? fallbackCurrency,
    from_price: fees?.from_price != null ? String(fees.from_price) : '',
    tiers: (fees?.tiers ?? []).map((t) => ({
      ...newTierDraft(t.label),
      custom: !labels.includes(t.label),
      price: String(t.price),
      is_early_bird: !!t.is_early_bird,
      early_bird_deadline: t.early_bird_deadline ?? '',
    })),
  }
}

/** http(s) URL safe to put in an href, or null. Never render user URLs unchecked. */
export function safeHref(url: unknown): string | null {
  return typeof url === 'string' ? normalizeUrl(url) : null
}

// ---------------------------------------------------------------- approval gate

export interface ApprovalCheck {
  ok: boolean
  /** Why approval is refused (ok = false). */
  reason?: string
  /** Non-blocking caution (ok = true). */
  warning?: string
}

const OPEN_STATUSES: ContributionStatus[] = ['pending', 'needs_info']

/**
 * Security control: `skipped` means the enrichment job rejected the organiser
 * URL as unsafe (non-http, private address, bad redirect chain). Those never
 * get approved from the UI because the daily remediator would later fetch the
 * stored URL. Other incomplete enrichment only warns.
 */
export function canApprove(c: Pick<Contribution, 'status' | 'enrichment_status'>): ApprovalCheck {
  if (!OPEN_STATUSES.includes(c.status)) {
    return { ok: false, reason: `This item is already ${c.status.replace('_', ' ')}.` }
  }
  const es: EnrichmentStatus = c.enrichment_status
  if (es === 'skipped') {
    return {
      ok: false,
      reason:
        'The organiser URL was rejected as unsafe by the automatic check, so this cannot be approved. Reject it, or ask the submitter for a different link.',
    }
  }
  if (es === 'blocked') return { ok: true, warning: 'The organiser site blocked the automatic check. Verify the details by hand before approving.' }
  if (es === 'failed') return { ok: true, warning: 'The automatic check failed. Verify the details by hand before approving.' }
  if (es === 'waiting') return { ok: true, warning: 'The automatic check has not run yet. Verify the details by hand, or wait for it.' }
  return { ok: true }
}

// ---------------------------------------------------------------- unchecked override

export interface OverrideCheck {
  needed: boolean
  reason?: string
}

function sameUrl(a: string, b: string): boolean {
  return (normalizeUrl(a) ?? a.trim()) === (normalizeUrl(b) ?? b.trim())
}

/**
 * Mirrors the database publish gate (migration 20261018000004). Approving or
 * merging needs an explicit `approve_unchecked` confirmation when the
 * enrichment job has not run (`waiting`), or when the organiser URL being
 * published differs from both URLs the job checked. `skipped` is never
 * overridable (canApprove refuses it), so it reports not-needed here.
 */
export function needsOverride(
  c: { enrichment_status: EnrichmentStatus; enrichment?: EnrichmentInput },
  finalOrganiserUrl: string | null | undefined
): OverrideCheck {
  if (c.enrichment_status === 'skipped') return { needed: false }
  if (c.enrichment_status === 'waiting') {
    return { needed: true, reason: 'This organiser link has not been safety-checked yet.' }
  }
  const checked = typeof c.enrichment?._checked_url === 'string' ? c.enrichment._checked_url : null
  const submitted = typeof c.enrichment?._submitted_url === 'string' ? c.enrichment._submitted_url : null
  if ((checked || submitted) && !isBlank(finalOrganiserUrl)) {
    const url = String(finalOrganiserUrl)
    const matches = (checked && sameUrl(url, checked)) || (submitted && sameUrl(url, submitted))
    if (!matches) return { needed: true, reason: 'The organiser link was changed after the safety check, so the new link has not been checked.' }
  }
  return { needed: false }
}

// ---------------------------------------------------------------- domain signals

export interface DomainSignals {
  organiserDomain: string | null
  bookingDomain: string | null
  /** Booking and organiser domains are both present and differ. */
  mismatch: boolean
  /** No existing listing shares the organiser domain. null = could not tell (directory not searched yet or failed). */
  unseen: boolean | null
}

export function hostnameOf(url: unknown): string | null {
  const n = typeof url === 'string' ? normalizeUrl(url) : null
  return n ? new URL(n).hostname.toLowerCase().replace(/^www\./, '') : null
}

const SECOND_LEVEL = new Set(['co', 'ac', 'org', 'nhs', 'gov', 'com', 'net', 'edu', 'sch'])

/** Registrable label to search the directory by: "www.rcseng.ac.uk" -> "rcseng", "esmo.org" -> "esmo". */
export function domainLabel(host: string | null): string | null {
  if (!host) return null
  const parts = host.split('.')
  if (parts.length < 2) return parts[0] || null
  const tld = parts[parts.length - 1]
  const sld = parts[parts.length - 2]
  if (parts.length >= 3 && tld.length === 2 && SECOND_LEVEL.has(sld)) return parts[parts.length - 3]
  return sld
}

/**
 * Provenance hints for the organiser/booking links in the final payload.
 * Heuristic: `rows` are directory search hits for the organiser domain label,
 * so "unseen" means no hit shares the domain, not proof the domain is new.
 */
export function domainSignals(finalPayload: unknown, rows: DuplicateRow[] | null): DomainSignals {
  const f = userFields(finalPayload)
  const organiserDomain = hostnameOf(f.organiser_url)
  const bookingDomain = hostnameOf(f.booking_url)
  const mismatch = !!organiserDomain && !!bookingDomain && organiserDomain !== bookingDomain
  let unseen: boolean | null = null
  if (organiserDomain && rows) {
    unseen = !rows.some((r) => !!r.organiserUrl && sameDomain(r.organiserUrl, `https://${organiserDomain}`))
  }
  return { organiserDomain, bookingDomain, mismatch, unseen }
}

// ---------------------------------------------------------------- duplicates

/** Normalised candidate row (the shape /api/directory returns, trimmed). */
export interface DuplicateRow {
  id: number
  name: string
  startDate: string | null
  organiserUrl: string | null
  city?: string | null
}

export type DuplicateReason = 'same_domain' | 'similar_name'
export interface DuplicateCandidate extends DuplicateRow {
  reasons: DuplicateReason[]
}

const STOP_WORDS = new Set([
  'the', 'and', 'for', 'with', 'of', 'in', 'on', 'at', 'to', 'a', 'an',
  'annual', 'conference', 'congress', 'meeting', 'symposium', 'course', 'workshop', 'international', 'national',
  'society', 'association', 'college', 'royal', 'update', 'summit', 'forum', 'event', 'virtual', 'online',
])

/** Lower-case words of ≥ 3 letters that are not generic event vocabulary; digits-only tokens (years) dropped. */
export function significantWords(name: string | null | undefined): string[] {
  if (!name) return []
  const words = name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length >= 3 && !/^\d+$/.test(w) && !STOP_WORDS.has(w))
  return [...new Set(words)]
}

function dayDiff(a: string | null | undefined, b: string | null | undefined): number | null {
  if (!a || !b) return null
  const da = Date.parse(`${a.slice(0, 10)}T00:00:00Z`)
  const db = Date.parse(`${b.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(da) || Number.isNaN(db)) return null
  return Math.abs(da - db) / 86_400_000
}

/**
 * A listing is a likely duplicate when it is on the same site as the
 * submitted organiser URL, or its name shares at least two significant words
 * with the submitted name and it starts within 30 days of it.
 */
export function duplicateCandidates(payload: unknown, rows: DuplicateRow[]): DuplicateCandidate[] {
  const u = userFields(payload)
  const name = typeof u.conference_name === 'string' ? u.conference_name : ''
  const url = typeof u.organiser_url === 'string' ? u.organiser_url : ''
  const start = typeof u.start_date === 'string' ? u.start_date : null
  const mine = new Set(significantWords(name))

  const out: DuplicateCandidate[] = []
  for (const row of rows) {
    const reasons: DuplicateReason[] = []
    if (url && row.organiserUrl && sameDomain(url, row.organiserUrl)) reasons.push('same_domain')
    const shared = significantWords(row.name).filter((w) => mine.has(w)).length
    const dd = dayDiff(start, row.startDate)
    if (shared >= 2 && dd !== null && dd <= 30) reasons.push('similar_name')
    if (reasons.length) out.push({ ...row, reasons })
  }
  // Both reasons first, then by closeness in time.
  return out.sort(
    (a, b) =>
      b.reasons.length - a.reasons.length ||
      (dayDiff(start, a.startDate) ?? 9999) - (dayDiff(start, b.startDate) ?? 9999)
  )
}

/** Accepts the camelCase DirectoryEvent rows or snake_case conference rows. */
export function toDuplicateRow(r: Record<string, unknown>): DuplicateRow | null {
  const id = Number(r.id)
  if (!Number.isFinite(id)) return null
  return {
    id,
    name: String(r.name ?? r.conference_name ?? ''),
    startDate: (r.startDate ?? r.start_date ?? null) as string | null,
    organiserUrl: (r.organiserUrl ?? r.organiser_url ?? r.source_url ?? null) as string | null,
    city: (r.city ?? null) as string | null,
  }
}

// ---------------------------------------------------------------- misc

/** Reason text must be meaningful: ≥ 5 characters after trimming. */
export function validReason(s: string): boolean {
  return s.trim().length >= 5
}

export type QueueTab = 'pending' | 'needs_info' | 'published' | 'rejected' | 'expired' | 'hidden'

export const TAB_STATUSES: Record<QueueTab, ContributionStatus[]> = {
  pending: ['pending'],
  needs_info: ['needs_info'],
  published: ['published', 'merged'],
  rejected: ['rejected'],
  expired: ['expired'],
  hidden: ['hidden'],
}

export const TAB_LABEL: Record<QueueTab, string> = {
  pending: 'Pending',
  needs_info: 'Needs info',
  published: 'Published',
  rejected: 'Rejected',
  expired: 'Expired',
  hidden: 'Hidden',
}

export const TAB_ORDER: QueueTab[] = ['pending', 'needs_info', 'published', 'rejected', 'expired', 'hidden']

export function tabOf(status: ContributionStatus): QueueTab {
  return status === 'merged' ? 'published' : (status as QueueTab)
}

/** "3 h", "2 d" style age for dense tables. */
export function ageLabel(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const mins = Math.max(0, Math.floor((now - t) / 60_000))
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins} min`
  const hours = Math.floor(mins / 60)
  if (hours < 48) return `${hours} h`
  return `${Math.floor(hours / 24)} d`
}
