// src/lib/format.ts
// Display formatting shared by the directory primitives. Pure functions, no
// React — so W2 can reuse them in server components, sorting and tests.

import { currencySymbol } from './conference-helpers'

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

/** Parse a `YYYY-MM-DD` string without letting the local timezone shift the day. */
export function parseIsoDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

export interface DateParts {
  day: string
  month: string
  year: number
}

export function dateParts(iso: string | null | undefined): DateParts | null {
  const d = parseIsoDate(iso)
  if (!d) return null
  return { day: String(d.getDate()), month: MONTHS[d.getMonth()], year: d.getFullYear() }
}

/**
 * Compact one-line range for the row meta / card:
 *   same day        → "13 Nov 2026"
 *   same month      → "13–15 Nov 2026"
 *   crosses a month → "30 Nov – 2 Dec 2026"
 *   crosses a year  → "30 Dec 2026 – 2 Jan 2027"
 */
export function formatDateRange(startIso: string | null, endIso: string | null): string {
  const s = parseIsoDate(startIso)
  if (!s) return 'Date TBC'
  const e = parseIsoDate(endIso)
  const fmt = (d: Date, withYear = true) =>
    `${d.getDate()} ${MONTHS[d.getMonth()][0]}${MONTHS[d.getMonth()].slice(1).toLowerCase()}${withYear ? ` ${d.getFullYear()}` : ''}`

  if (!e || e.getTime() === s.getTime()) return fmt(s)
  if (s.getFullYear() !== e.getFullYear()) return `${fmt(s)} – ${fmt(e)}`
  if (s.getMonth() !== e.getMonth()) return `${fmt(s, false)} – ${fmt(e)}`
  return `${s.getDate()}–${fmt(e)}`
}

/** Whole days from today to `iso`. Negative = past. Null when there is no date. */
export function daysUntil(iso: string | null | undefined): number | null {
  const d = parseIsoDate(iso)
  if (!d) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}

/** "in 6 days" / "tomorrow" / "today" / "3 days ago" */
export function relativeDays(days: number): string {
  if (days === 0) return 'today'
  if (days === 1) return 'tomorrow'
  if (days === -1) return 'yesterday'
  if (days > 0) return `in ${days} days`
  return `${Math.abs(days)} days ago`
}

/**
 * Money with the right symbol and no pointless decimals — clinicians scan
 * "£185", not "£185.00". Non-integer amounts keep two places.
 */
export function formatMoney(amount: number, currency?: string | null): string {
  const symbol = currencySymbol(currency)
  const value = Number.isInteger(amount) ? String(amount) : amount.toFixed(2)
  return `${symbol}${value}`
}
