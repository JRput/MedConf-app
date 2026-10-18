// src/lib/community/fees-draft.ts
// Form-state <-> payload conversion for the fee quick editor. Drafts keep
// prices as strings so a half-typed "12." is not coerced away.

import { CURRENCIES, FEE_LABELS, MAX_TIERS, feesSchema, type FeesOutput } from './schema'

export interface TierDraft {
  /** Stable React key; not sent anywhere. */
  key: string
  label: string
  /** True when the user chose "Other" and types their own label. */
  custom: boolean
  price: string
  is_early_bird: boolean
  early_bird_deadline: string
}

export interface FeesDraft {
  currency: string
  from_price: string
  tiers: TierDraft[]
}

let seq = 0
export function newTierDraft(label: string = FEE_LABELS[0]): TierDraft {
  seq += 1
  return { key: `t${seq}-${Date.now().toString(36)}`, label, custom: false, price: '', is_early_bird: false, early_bird_deadline: '' }
}

export function emptyFeesDraft(currency = 'GBP'): FeesDraft {
  return { currency: (CURRENCIES as readonly string[]).includes(currency) ? currency : 'GBP', from_price: '', tiers: [] }
}

export function isFeesDraftEmpty(d: FeesDraft): boolean {
  return d.from_price.trim() === '' && d.tiers.every((t) => t.price.trim() === '' && (t.custom ? t.label.trim() === '' : true))
}

function toNumber(s: string): number | undefined {
  const t = s.trim()
  if (t === '') return undefined
  const n = Number(t)
  return Number.isFinite(n) ? n : Number.NaN
}

/** Raw (pre-zod) payload built from a draft; rows with no price AND no custom label are dropped. */
export function feesDraftToRaw(d: FeesDraft) {
  const tiers = d.tiers
    .filter((t) => t.price.trim() !== '' || (t.custom && t.label.trim() !== ''))
    .map((t) => ({
      label: t.label.trim(),
      price: toNumber(t.price) as number,
      is_early_bird: t.is_early_bird,
      ...(t.is_early_bird && t.early_bird_deadline ? { early_bird_deadline: t.early_bird_deadline } : {}),
    }))
  const from = toNumber(d.from_price)
  return { currency: d.currency, ...(from !== undefined ? { from_price: from } : {}), tiers }
}

export interface FeesValidation {
  /** Keys: 'currency' | 'from_price' | 'tiers' | `tiers.${i}.${label|price|early_bird_deadline}` (i indexes the filtered rows -> mapped back to draft rows). */
  errors: Record<string, string>
  payload: FeesOutput | null
}

/** Validate a draft. Returns field errors keyed to DRAFT row indexes, and the zod-clean payload when valid. */
export function validateFeesDraft(d: FeesDraft): FeesValidation {
  const errors: Record<string, string> = {}
  const keptIdx: number[] = []
  d.tiers.forEach((t, i) => {
    if (t.price.trim() !== '' || (t.custom && t.label.trim() !== '')) keptIdx.push(i)
  })
  // Rows that exist but are blank: flag only when the user has filled something elsewhere in the row.
  const raw = feesDraftToRaw(d)
  const res = feesSchema.safeParse(raw)
  if (res.success) return { errors, payload: res.data }
  for (const issue of res.error.issues) {
    const [first, idx, field] = issue.path
    if (first === 'tiers' && typeof idx === 'number' && typeof field === 'string') {
      const draftIdx = keptIdx[idx] ?? idx
      const key = `tiers.${draftIdx}.${field}`
      if (!errors[key]) errors[key] = tidy(issue.message, field)
    } else if (first === 'tiers') {
      errors.tiers = issue.message
    } else if (typeof first === 'string') {
      errors[first] = tidy(issue.message, first)
    }
  }
  // A custom-label row with a label but no price is the common half-finished state.
  d.tiers.forEach((t, i) => {
    if (t.custom && t.label.trim() !== '' && t.price.trim() === '') errors[`tiers.${i}.price`] = 'Enter a price (0 if free)'
  })
  return { errors, payload: null }
}

function tidy(message: string, field: string): string {
  if (/expected number/i.test(message) || /invalid input/i.test(message)) {
    if (field === 'price') return 'Enter a price (0 if free)'
    if (field === 'from_price') return 'Enter a number'
  }
  return message
}

export { MAX_TIERS }
