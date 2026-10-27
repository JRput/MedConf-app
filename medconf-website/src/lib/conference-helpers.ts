// src/lib/conference-helpers.ts
// Tiny derived helpers so the UI is robust against stale stored flags.
//
// abstract_open in the DB can drift out of sync — the scraper sets it
// from the source page's text ("abstracts open"), but the source rarely
// updates that text the moment the deadline passes. The deadline DATE
// is the source of truth, so we treat the stored bool as a hint and
// gate it on the date when rendering.

import type { Conference, CourseSession } from './types'

/** Courses and degrees are multi-session programmes: they show sessions and never get the abstracts prompt. */
export function isCourseLike(eventType: string | null | undefined): boolean {
  return eventType === 'course' || eventType === 'degree'
}

/**
 * True only when abstracts are genuinely still being accepted right now.
 *
 * Order of precedence (a real date beats a free-text note):
 *  1. abstract_open must be true
 *  2. If abstract_deadline is set, it dictates: open ONLY when today-or-later
 *  3. If abstract_deadline is null and abstract_deadline_note is set,
 *     treat as curator-confirmed open with no published date
 *  4. Otherwise closed
 *
 * The validator at insert/update time also enforces #2 — but the helper
 * runs the check independently so a stale row (deadline ticked past today
 * since the last scrape) is rendered correctly without waiting for the
 * cleanup cron.
 */
export function isAbstractEffectivelyOpen(c: Conference): boolean {
  if (!c.abstract_open) return false
  if (c.abstract_deadline) {
    const today = new Date().toISOString().slice(0, 10)
    return c.abstract_deadline >= today
  }
  if (c.abstract_deadline_note) return true
  return false
}

/**
 * Days remaining until the abstract deadline. Negative = past, null = no deadline.
 */
export function daysUntilDeadline(c: Conference): number | null {
  if (!c.abstract_deadline) return null
  const diff = (new Date(c.abstract_deadline).getTime() - Date.now()) / 86_400_000
  return Math.ceil(diff)
}

// Currencies whose narrow symbol is unambiguous for our audience. Everything
// else uses the en-GB "symbol" form, which disambiguates ("A$", "HK$", "US$"
// is avoided only for USD) or falls back to the ISO code ("SGD", "CHF", "SEK").
const NARROW_OK = new Set(['GBP', 'EUR', 'USD', 'INR', 'KRW', 'JPY'])

/** Normalised ISO-4217-shaped code, or null when absent / not three letters. */
export function normaliseCurrency(code: string | undefined | null): string | null {
  const c = (code ?? '').trim().toUpperCase()
  return /^[A-Z]{3}$/.test(c) ? c : null
}

/**
 * Build an en-GB currency formatter, or null when the runtime does not know
 * the code (or it is the "no currency" placeholder XXX). Prefers
 * `narrowSymbol`, falling back to `symbol` where the runtime lacks it.
 */
export function currencyFormatter(
  code: string,
  minimumFractionDigits?: number
): Intl.NumberFormat | null {
  if (code === 'XXX') return null
  const display = NARROW_OK.has(code) ? 'narrowSymbol' : 'symbol'
  for (const currencyDisplay of [display, 'symbol'] as const) {
    try {
      return new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: code,
        currencyDisplay,
        ...(minimumFractionDigits === undefined ? {} : { minimumFractionDigits }),
      })
    } catch {
      /* try the next display, then give up */
    }
  }
  return null
}

/** Currency code (ISO 4217) → display symbol; alphabetic symbols and unknown
 * codes come back as "CODE " (trailing space) so "SGD 250" reads correctly.
 * Null / empty / malformed → '' (callers must flag the unknown currency). */
export function currencySymbol(code: string | undefined | null): string {
  const c = normaliseCurrency(code)
  if (!c) return ''
  const fmt = currencyFormatter(c)
  const sym = fmt?.formatToParts(0).find((p) => p.type === 'currency')?.value
  if (!sym || sym === '\u00a4') return `${c} `
  return /[A-Za-z]$/.test(sym) ? `${sym} ` : sym
}

export interface PriceSummary {
  min: number | null
  max: number | null
  /** Currency the min/max are in; null = the tiers carry no usable currency. */
  currency: string | null
  /** Tiers priced in some other currency and therefore left out of min/max. */
  otherCount: number
}

/**
 * One honest price range for a set of tiers. Numbers from different
 * currencies are never mixed: a single-currency set gives its range; a mixed
 * set gives the GBP range if any GBP tier exists, else the most frequent
 * currency (ties: first seen), plus a count of the tiers left out.
 */
export function summarisePrices(
  tiers: { price_gbp: number | string | null; currency?: string | null }[]
): PriceSummary {
  const groups = new Map<string, number[]>() // '' = unknown currency
  let total = 0
  for (const t of tiers) {
    const n = Number(t.price_gbp)
    if (t.price_gbp === null || t.price_gbp === '' || !Number.isFinite(n)) continue
    const key = normaliseCurrency(t.currency) ?? ''
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(n)
    total++
  }
  if (groups.size === 0) return { min: null, max: null, currency: null, otherCount: 0 }
  let chosen: string
  if (groups.size === 1 || groups.has('GBP')) {
    chosen = groups.size === 1 ? [...groups.keys()][0] : 'GBP'
  } else {
    chosen = [...groups.entries()].reduce((best, cur) => (cur[1].length > best[1].length ? cur : best))[0]
  }
  const nums = groups.get(chosen)!
  return {
    min: Math.min(...nums),
    max: Math.max(...nums),
    currency: chosen || null,
    otherCount: total - nums.length,
  }
}

/**
 * Whether the conference has any abstract submission info worth showing.
 * If no deadline AND no curator note, we don't render the abstract panel
 * at all — "Closed with no date" tells the user nothing useful.
 */
export function hasAbstractInfo(c: Conference): boolean {
  return !!(c.abstract_deadline || c.abstract_deadline_note)
}

/**
 * Filter and sort a course's sessions to surface the ones a user can act on
 * right now (today or later, sorted soonest first).
 */
export function upcomingSessions(sessions: CourseSession[] | undefined): CourseSession[] {
  if (!sessions) return []
  const today = new Date().toISOString().slice(0, 10)
  return sessions
    .filter(s => s.start_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date))
}

/**
 * Pick the headline "next session" for a course card. Prefers the soonest
 * non-sold-out upcoming session; falls back to the soonest sold-out session
 * so the card can still surface a date instead of going blank.
 */
export function nextAvailableSession(sessions: CourseSession[] | undefined): CourseSession | null {
  const upcoming = upcomingSessions(sessions)
  if (upcoming.length === 0) return null
  const available = upcoming.find(s => s.availability_status !== 'sold_out')
  return available ?? upcoming[0]
}

export function courseSessionSummary(sessions: CourseSession[] | undefined) {
  const upcoming = upcomingSessions(sessions)
  return {
    upcoming,
    total: upcoming.length,
    available: upcoming.filter(s => s.availability_status !== 'sold_out').length,
    next: nextAvailableSession(sessions),
    allSoldOut: upcoming.length > 0 && upcoming.every(s => s.availability_status === 'sold_out'),
  }
}
