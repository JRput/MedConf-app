// src/lib/calendar.ts
// The month-grid engine behind /calendar. Pure functions, no React, no Date
// arithmetic that a timezone can move — so the layout is unit-testable and
// identical for a user in Lisbon and a user in Auckland.
//
// WHY STRING DATES. Every date in this product is a day-precision
// `YYYY-MM-DD` from Postgres (`conferences.start_date` et al). The moment you
// put one through `new Date('2026-03-29')` and read it back with local
// getters you inherit two bugs: the string parses as UTC midnight, so
// anywhere west of Greenwich reads the day BEFORE; and adding days across a
// DST boundary with `setHours`/`setDate` on a local Date can land on the same
// calendar day twice (28 Mar → 29 Mar is 23h in Europe/London). So the only
// Date instances here are built with `Date.UTC` and read with `getUTC*`,
// which makes every month exactly 24h-per-day regardless of the viewer, and
// the public surface is strings in, strings out.
//
// The one deliberately local-time function is `todayIso()` — "today" is the
// user's wall-clock day, not UTC's.

/** A single grid cell. `inMonth` is false for the leading/trailing days that pad the first and last weeks. */
export interface DayCell {
  /** `YYYY-MM-DD` */
  iso: string
  /** 1–31 */
  day: number
  /** 1–12 */
  month: number
  year: number
  /** Whether this cell belongs to the month the matrix was built for. */
  inMonth: boolean
  /** Saturday or Sunday, for the quiet weekend tint. */
  isWeekend: boolean
}

/** Always exactly 7 cells, left-to-right in display order. */
export type WeekRow = DayCell[]

export interface MonthMatrix {
  year: number
  /** 1–12 */
  month: number
  weeks: WeekRow[]
  /** First cell's iso (may be in the previous month). */
  start: string
  /** Last cell's iso (may be in the next month). */
  end: string
  weekStartsOn: WeekStart
}

/** 0 = Sunday, 1 = Monday. The UK (and this product) default is Monday. */
export type WeekStart = 0 | 1

const YMD = /^(\d{4})-(\d{2})-(\d{2})$/

export function isValidIsoDate(iso: string | null | undefined): boolean {
  if (!iso || !YMD.test(iso)) return false
  const { year, month, day } = splitIso(iso)!
  if (month < 1 || month > 12 || day < 1) return false
  return day <= daysInMonth(year, month)
}

function splitIso(iso: string): { year: number; month: number; day: number } | null {
  const m = YMD.exec(iso)
  if (!m) return null
  return { year: Number(m[1]), month: Number(m[2]), day: Number(m[3]) }
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** Build `YYYY-MM-DD` from parts. Does not normalise — callers pass valid parts. */
export function toIso(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, '0')}-${pad2(month)}-${pad2(day)}`
}

export function daysInMonth(year: number, month: number): number {
  // Day 0 of the next month is the last day of this one.
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

/** The viewer's local calendar day as `YYYY-MM-DD`. */
export function todayIso(now: Date = new Date()): string {
  return toIso(now.getFullYear(), now.getMonth() + 1, now.getDate())
}

/**
 * Shift a day-precision date by whole days. DST-free: the arithmetic happens
 * in UTC where every day is exactly 24 hours.
 */
export function addDays(iso: string, delta: number): string {
  const parts = splitIso(iso)
  if (!parts) throw new Error(`addDays: not a YYYY-MM-DD date: ${iso}`)
  const d = new Date(Date.UTC(parts.year, parts.month - 1, parts.day))
  d.setUTCDate(d.getUTCDate() + delta)
  return toIso(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate())
}

/** Whole days from `a` to `b`. Negative when `b` is earlier. */
export function daysBetween(a: string, b: string): number {
  const pa = splitIso(a)
  const pb = splitIso(b)
  if (!pa || !pb) throw new Error(`daysBetween: not YYYY-MM-DD dates: ${a}, ${b}`)
  const ta = Date.UTC(pa.year, pa.month - 1, pa.day)
  const tb = Date.UTC(pb.year, pb.month - 1, pb.day)
  return Math.round((tb - ta) / 86_400_000)
}

/** 0 = Sunday … 6 = Saturday, for a day-precision date. */
export function isoWeekday(iso: string): number {
  const parts = splitIso(iso)
  if (!parts) throw new Error(`isoWeekday: not a YYYY-MM-DD date: ${iso}`)
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day)).getUTCDay()
}

/** Which grid column a date falls in, given where the week starts. */
export function columnOf(iso: string, weekStartsOn: WeekStart = 1): number {
  return (isoWeekday(iso) - weekStartsOn + 7) % 7
}

/** Step a (year, month) pair by whole months, rolling the year over. */
export function addMonths(year: number, month: number, delta: number): { year: number; month: number } {
  const zero = year * 12 + (month - 1) + delta
  return { year: Math.floor(zero / 12), month: (((zero % 12) + 12) % 12) + 1 }
}

/** `2026-11` — the `m=` URL param and the agenda's grouping key. */
export function monthKey(year: number, month: number): string {
  return `${String(year).padStart(4, '0')}-${pad2(month)}`
}

export function monthKeyOf(iso: string): string {
  return iso.slice(0, 7)
}

/** Parse a `YYYY-MM` URL param. Returns null for anything malformed so the caller can fall back to today. */
export function parseMonthKey(key: string | null | undefined): { year: number; month: number } | null {
  if (!key || !/^\d{4}-\d{2}$/.test(key)) return null
  const year = Number(key.slice(0, 4))
  const month = Number(key.slice(5, 7))
  if (month < 1 || month > 12) return null
  return { year, month }
}

/**
 * The month's day grid, as whole weeks.
 *
 * `fixedWeeks` (default true) always emits 6 rows. A month needs 4–6 rows
 * depending on where it starts, and letting the row count vary makes the grid
 * jump in height every time you page months — which is exactly the motion you
 * notice when holding down the Next key. Six rows costs one mostly-empty row
 * in short months and keeps the header, legend and footer still.
 */
export function monthMatrix(
  year: number,
  month: number,
  { weekStartsOn = 1, fixedWeeks = true }: { weekStartsOn?: WeekStart; fixedWeeks?: boolean } = {}
): MonthMatrix {
  const first = toIso(year, month, 1)
  const gridStart = addDays(first, -columnOf(first, weekStartsOn))

  const last = toIso(year, month, daysInMonth(year, month))
  const naturalWeeks = Math.ceil((columnOf(first, weekStartsOn) + daysInMonth(year, month)) / 7)
  const weekCount = fixedWeeks ? 6 : naturalWeeks

  const weeks: WeekRow[] = []
  for (let w = 0; w < weekCount; w++) {
    const row: WeekRow = []
    for (let d = 0; d < 7; d++) {
      const iso = addDays(gridStart, w * 7 + d)
      const parts = splitIso(iso)!
      const weekday = isoWeekday(iso)
      row.push({
        iso,
        day: parts.day,
        month: parts.month,
        year: parts.year,
        inMonth: iso >= first && iso <= last,
        isWeekend: weekday === 0 || weekday === 6,
      })
    }
    weeks.push(row)
  }

  return {
    year,
    month,
    weeks,
    start: weeks[0][0].iso,
    end: weeks[weeks.length - 1][6].iso,
    weekStartsOn,
  }
}

/* ========================================================== SPAN LAYOUT === */

/** The minimum an event needs to be placed on the grid. */
export interface SpanInput {
  id: number
  startDate: string | null
  endDate?: string | null
}

/**
 * One event's occupancy of one week row. A single-day event is a segment of
 * length 1 — deliberately the same shape as a multi-day bar so there is one
 * layout pass and one lane stack, not a chip system and a bar system fighting
 * over the same vertical space.
 */
export interface Segment<T extends SpanInput = SpanInput> {
  event: T
  /** Index of the week row in `matrix.weeks`. */
  week: number
  /** First occupied column, 0–6. */
  startCol: number
  /** Last occupied column, 0–6, inclusive. */
  endCol: number
  /** Columns covered — `endCol - startCol + 1`. */
  length: number
  /** The event began before this row (clip the left edge, show a back arrow). */
  continuesBefore: boolean
  /** The event runs past this row (clip the right edge, show a forward arrow). */
  continuesAfter: boolean
  /** Vertical slot within the row, 0-based. */
  lane: number
  /** True when the event occupies more than one day in total (not just in this row). */
  isMultiDay: boolean
}

export interface WeekLayout<T extends SpanInput = SpanInput> {
  week: number
  /** Segments that fit within `maxLanes`, ready to render. */
  segments: Segment<T>[]
  /** Segments pushed past `maxLanes` — the "+N more" popover's contents. */
  hidden: Segment<T>[]
  /** Lanes the row would need to show everything. */
  laneCount: number
  /** `iso` → how many events are hidden on that specific day. */
  hiddenCountByDay: Record<string, number>
}

/** Normalised date span for an event, or null when it cannot be placed. */
function spanOf(e: SpanInput): { start: string; end: string } | null {
  if (!isValidIsoDate(e.startDate)) return null
  const start = e.startDate as string
  // An end date that is missing, malformed, or (from bad source data) earlier
  // than the start collapses to a single day rather than drawing backwards.
  const end = isValidIsoDate(e.endDate) && (e.endDate as string) >= start ? (e.endDate as string) : start
  return { start, end }
}

/**
 * Lay events out across a month matrix, row by row, assigning lanes so no two
 * segments overlap.
 *
 * Ordering drives the result, so it is fixed and total: earlier start first,
 * then longer span first (long congresses get the top lane, which is what
 * makes a continuing bar hold the same lane across week rows most of the
 * time), then id, so the layout never reshuffles between renders.
 *
 * `maxLanes` splits each row into visible and hidden rather than dropping
 * anything — the renderer needs the hidden ones for its overflow popover.
 */
export function placeSpans<T extends SpanInput>(
  events: readonly T[],
  matrix: MonthMatrix,
  { maxLanes = Infinity }: { maxLanes?: number } = {}
): WeekLayout<T>[] {
  const placeable = events
    .map((event) => ({ event, span: spanOf(event) }))
    .filter((x): x is { event: T; span: { start: string; end: string } } => x.span !== null)
    // Only events that touch the grid at all.
    .filter((x) => x.span.end >= matrix.start && x.span.start <= matrix.end)
    .sort((a, b) => {
      if (a.span.start !== b.span.start) return a.span.start < b.span.start ? -1 : 1
      const lenA = daysBetween(a.span.start, a.span.end)
      const lenB = daysBetween(b.span.start, b.span.end)
      if (lenA !== lenB) return lenB - lenA
      return a.event.id - b.event.id
    })

  return matrix.weeks.map((row, week) => {
    const weekStart = row[0].iso
    const weekEnd = row[6].iso

    // Lane occupancy as a 7-slot boolean per lane.
    const lanes: boolean[][] = []
    const segments: Segment<T>[] = []
    const hidden: Segment<T>[] = []
    const hiddenCountByDay: Record<string, number> = {}

    for (const { event, span } of placeable) {
      if (span.end < weekStart || span.start > weekEnd) continue

      const visibleStart = span.start < weekStart ? weekStart : span.start
      const visibleEnd = span.end > weekEnd ? weekEnd : span.end
      const startCol = columnOf(visibleStart, matrix.weekStartsOn)
      const endCol = columnOf(visibleEnd, matrix.weekStartsOn)

      let lane = lanes.findIndex((slots) => slots.slice(startCol, endCol + 1).every((taken) => !taken))
      if (lane === -1) {
        lane = lanes.length
        lanes.push(new Array(7).fill(false))
      }
      for (let c = startCol; c <= endCol; c++) lanes[lane][c] = true

      const segment: Segment<T> = {
        event,
        week,
        startCol,
        endCol,
        length: endCol - startCol + 1,
        continuesBefore: span.start < weekStart,
        continuesAfter: span.end > weekEnd,
        lane,
        isMultiDay: span.end > span.start,
      }

      if (lane < maxLanes) {
        segments.push(segment)
      } else {
        hidden.push(segment)
        for (let c = startCol; c <= endCol; c++) {
          const iso = row[c].iso
          hiddenCountByDay[iso] = (hiddenCountByDay[iso] ?? 0) + 1
        }
      }
    }

    return { week, segments, hidden, laneCount: lanes.length, hiddenCountByDay }
  })
}

/**
 * `iso` → events whose abstract deadline falls on that day, for the days the
 * matrix covers. Separate from the span layout: a deadline is a point marker
 * on a date, not a block of time, and doctors read it as a different kind of
 * object from the event itself.
 */
export function deadlinesByDay<T extends { id: number; abstractDeadline?: string | null }>(
  events: readonly T[],
  range: { start: string; end: string }
): Record<string, T[]> {
  const out: Record<string, T[]> = {}
  for (const e of events) {
    const d = e.abstractDeadline
    if (!isValidIsoDate(d)) continue
    const iso = d as string
    if (iso < range.start || iso > range.end) continue
    ;(out[iso] ??= []).push(e)
  }
  return out
}

/**
 * Events occupying a specific day — the mobile week strip's dot counts and
 * day list. A multi-day congress counts on every day it runs, not just its
 * first, which is the whole point of asking "what have I got on Wednesday?".
 */
export function eventsOnDay<T extends SpanInput>(events: readonly T[], iso: string): T[] {
  return events.filter((e) => {
    const span = spanOf(e)
    return span !== null && span.start <= iso && span.end >= iso
  })
}

/** Events that overlap a given month at all — the header's "N events this month" count. */
export function eventsInMonth<T extends SpanInput>(events: readonly T[], year: number, month: number): T[] {
  const first = toIso(year, month, 1)
  const last = toIso(year, month, daysInMonth(year, month))
  return events.filter((e) => {
    const span = spanOf(e)
    if (!span) return false
    return span.end >= first && span.start <= last
  })
}

/* ============================================================== AGENDA ==== */

export interface MonthGroup<T> {
  /** `YYYY-MM` */
  key: string
  year: number
  /** 1–12 */
  month: number
  events: T[]
}

/**
 * Agenda grouping: dated events bucketed by the month they START in, in
 * chronological order, plus everything we cannot place.
 *
 * Undated saves are kept and surfaced separately rather than quietly dropped
 * — a saved event with no published date is still a real thing the user chose
 * to track, and inventing a date for it to sit on the grid would be a lie.
 */
export function groupByMonth<T extends SpanInput>(
  events: readonly T[],
  { from }: { from?: string } = {}
): { groups: MonthGroup<T>[]; undated: T[] } {
  const undated: T[] = []
  const byKey = new Map<string, MonthGroup<T>>()

  const dated = events.filter((e) => {
    const span = spanOf(e)
    if (!span) {
      undated.push(e)
      return false
    }
    // "Upcoming" means it has not finished yet — an in-progress congress
    // still belongs at the top of the agenda, not in the past.
    return from ? span.end >= from : true
  })

  dated.sort((a, b) => {
    const sa = spanOf(a)!
    const sb = spanOf(b)!
    if (sa.start !== sb.start) return sa.start < sb.start ? -1 : 1
    return a.id - b.id
  })

  for (const e of dated) {
    const start = spanOf(e)!.start
    const key = monthKeyOf(start)
    let group = byKey.get(key)
    if (!group) {
      group = { key, year: Number(key.slice(0, 4)), month: Number(key.slice(5, 7)), events: [] }
      byKey.set(key, group)
    }
    group.events.push(e)
  }

  return { groups: Array.from(byKey.values()), undated }
}

/* ============================================================== LABELS ==== */

/**
 * Locale-aware month and weekday names. The grid is Monday-first for the UK
 * but the LABELS follow the viewer's locale, so a user with a French browser
 * reads "novembre" over a Monday-first grid.
 */
export function monthLabel(year: number, month: number, locale?: string, opts: Intl.DateTimeFormatOptions = { month: 'long', year: 'numeric' }): string {
  return new Intl.DateTimeFormat(locale, { ...opts, timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, 1)))
}

/** Seven short weekday labels in display order, starting at `weekStartsOn`. */
export function weekdayLabels(weekStartsOn: WeekStart = 1, locale?: string, width: 'short' | 'narrow' = 'short'): string[] {
  const fmt = new Intl.DateTimeFormat(locale, { weekday: width, timeZone: 'UTC' })
  // 2024-01-07 was a Sunday, so +weekday lands on each day of the week.
  return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(Date.UTC(2024, 0, 7 + ((weekStartsOn + i) % 7)))))
}

/** Full weekday + date, for the side panel heading and `aria-label`s. */
export function longDateLabel(iso: string, locale?: string): string {
  const parts = splitIso(iso)
  if (!parts) return iso
  return new Intl.DateTimeFormat(locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(parts.year, parts.month - 1, parts.day)))
}
