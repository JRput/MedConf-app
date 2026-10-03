// src/lib/__tests__/calendar.test.ts
// The month-grid engine's contract. The cases that matter are the ones a
// hand-rolled calendar normally gets wrong: month boundaries, the leap year,
// DST weekends, and multi-day spans that cross a week row.
import { describe, expect, it } from 'vitest'
import {
  addDays,
  addMonths,
  columnOf,
  daysBetween,
  daysInMonth,
  deadlineCountdown,
  deadlinesByDay,
  eventsInMonth,
  eventsOnDay,
  groupByMonth,
  isValidIsoDate,
  isoWeekday,
  monthKey,
  monthMatrix,
  parseMonthKey,
  placeSpans,
  shortDateLabel,
  toIso,
  todayIso,
  upcomingDeadlines,
  weekdayLabels,
  type SpanInput,
} from '../calendar'

function ev(id: number, startDate: string | null, endDate?: string | null): SpanInput {
  return { id, startDate, endDate }
}

/** Flatten a week's visible segments to `id@lane:startCol-endCol` for terse assertions. */
function sig(segments: { event: { id: number }; lane: number; startCol: number; endCol: number }[]): string[] {
  return segments.map((s) => `${s.event.id}@${s.lane}:${s.startCol}-${s.endCol}`)
}

describe('date primitives', () => {
  it('validates YYYY-MM-DD and rejects impossible days', () => {
    expect(isValidIsoDate('2026-11-09')).toBe(true)
    expect(isValidIsoDate('2026-02-29')).toBe(false) // 2026 is not a leap year
    expect(isValidIsoDate('2024-02-29')).toBe(true) // 2024 is
    expect(isValidIsoDate('2026-13-01')).toBe(false)
    expect(isValidIsoDate('2026-11-31')).toBe(false)
    expect(isValidIsoDate('09/11/2026')).toBe(false)
    expect(isValidIsoDate(null)).toBe(false)
    expect(isValidIsoDate('')).toBe(false)
  })

  it('adds days across month, year and leap-day boundaries', () => {
    expect(addDays('2026-11-30', 1)).toBe('2026-12-01')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2027-01-01', -1)).toBe('2026-12-31')
    expect(addDays('2024-02-28', 1)).toBe('2024-02-29')
    expect(addDays('2026-02-28', 1)).toBe('2026-03-01')
    expect(addDays('2026-03-15', 0)).toBe('2026-03-15')
  })

  it('is immune to DST: the spring-forward and autumn-back weekends are still 24h days', () => {
    // Europe/London springs forward on 2026-03-29 and falls back on 2026-10-25.
    // Naive local-time arithmetic skips or repeats a day across these.
    expect(addDays('2026-03-28', 1)).toBe('2026-03-29')
    expect(addDays('2026-03-29', 1)).toBe('2026-03-30')
    expect(addDays('2026-10-24', 1)).toBe('2026-10-25')
    expect(addDays('2026-10-25', 1)).toBe('2026-10-26')
    expect(daysBetween('2026-03-01', '2026-04-01')).toBe(31)
    expect(daysBetween('2026-10-01', '2026-11-01')).toBe(31)
    // US DST dates differ again — same answer, because none of this is local.
    expect(daysBetween('2026-03-07', '2026-03-09')).toBe(2)
  })

  it('measures signed day distances', () => {
    expect(daysBetween('2026-11-09', '2026-11-12')).toBe(3)
    expect(daysBetween('2026-11-12', '2026-11-09')).toBe(-3)
    expect(daysBetween('2026-11-09', '2026-11-09')).toBe(0)
    expect(daysBetween('2026-12-31', '2027-01-01')).toBe(1)
  })

  it('knows weekdays and maps them to Monday-first columns', () => {
    expect(isoWeekday('2026-11-09')).toBe(1) // a Monday
    expect(isoWeekday('2026-11-15')).toBe(0) // the Sunday after
    expect(columnOf('2026-11-09', 1)).toBe(0) // Monday-first → column 0
    expect(columnOf('2026-11-15', 1)).toBe(6) // Sunday → last column
    expect(columnOf('2026-11-09', 0)).toBe(1) // Sunday-first → Monday is column 1
    expect(columnOf('2026-11-15', 0)).toBe(0)
  })

  it('counts days in a month including February in both year kinds', () => {
    expect(daysInMonth(2026, 2)).toBe(28)
    expect(daysInMonth(2024, 2)).toBe(29)
    expect(daysInMonth(2026, 11)).toBe(30)
    expect(daysInMonth(2026, 12)).toBe(31)
    expect(daysInMonth(2000, 2)).toBe(29) // century leap year
    expect(daysInMonth(1900, 2)).toBe(28) // century non-leap year
  })

  it('steps months and rolls the year over in both directions', () => {
    expect(addMonths(2026, 11, 1)).toEqual({ year: 2026, month: 12 })
    expect(addMonths(2026, 12, 1)).toEqual({ year: 2027, month: 1 })
    expect(addMonths(2026, 1, -1)).toEqual({ year: 2025, month: 12 })
    expect(addMonths(2026, 6, -18)).toEqual({ year: 2024, month: 12 })
    expect(addMonths(2026, 6, 0)).toEqual({ year: 2026, month: 6 })
  })

  it('round-trips the `m=` URL param and rejects junk', () => {
    expect(monthKey(2026, 11)).toBe('2026-11')
    expect(monthKey(2026, 3)).toBe('2026-03')
    expect(parseMonthKey('2026-11')).toEqual({ year: 2026, month: 11 })
    expect(parseMonthKey('2026-00')).toBeNull()
    expect(parseMonthKey('2026-13')).toBeNull()
    expect(parseMonthKey('2026-1')).toBeNull()
    expect(parseMonthKey('nope')).toBeNull()
    expect(parseMonthKey(null)).toBeNull()
  })

  it('reports today as a local calendar day, not a UTC one', () => {
    // A late-evening local time west of Greenwich is already "tomorrow" in UTC;
    // the grid's today ring must follow the viewer's wall clock.
    expect(todayIso(new Date(2026, 10, 9, 23, 30))).toBe('2026-11-09')
    expect(todayIso(new Date(2026, 0, 1, 0, 5))).toBe('2026-01-01')
    expect(/^\d{4}-\d{2}-\d{2}$/.test(todayIso())).toBe(true)
  })

  it('builds iso strings from parts with zero padding', () => {
    expect(toIso(2026, 3, 7)).toBe('2026-03-07')
    expect(toIso(2026, 12, 31)).toBe('2026-12-31')
  })
})

describe('monthMatrix', () => {
  it('starts on a Monday, pads both ends, and marks which cells are in-month', () => {
    // November 2026: the 1st is a Sunday, the 30th a Monday.
    const m = monthMatrix(2026, 11)
    expect(m.weeks).toHaveLength(6)
    expect(m.weeks.every((w) => w.length === 7)).toBe(true)
    expect(isoWeekday(m.start)).toBe(1)
    expect(m.start).toBe('2026-10-26') // the Monday before the 1st
    expect(m.weeks[0][6].iso).toBe('2026-11-01') // Sunday the 1st closes week 1
    expect(m.weeks[0][0].inMonth).toBe(false)
    expect(m.weeks[0][6].inMonth).toBe(true)
    expect(m.end).toBe('2026-12-06')
    expect(m.weeks[5][6].inMonth).toBe(false)
    // Every in-month cell, and only those, belongs to month 11.
    const inMonth = m.weeks.flat().filter((c) => c.inMonth)
    expect(inMonth).toHaveLength(30)
    expect(inMonth.every((c) => c.month === 11 && c.year === 2026)).toBe(true)
  })

  it('handles a month that starts exactly on the week start with no leading pad', () => {
    // 1 June 2026 is a Monday.
    const m = monthMatrix(2026, 6)
    expect(m.start).toBe('2026-06-01')
    expect(m.weeks[0][0].inMonth).toBe(true)
    expect(m.weeks[0][0].day).toBe(1)
  })

  it('covers February of a leap year and a non-leap year completely', () => {
    const leap = monthMatrix(2024, 2)
    const leapDays = leap.weeks.flat().filter((c) => c.inMonth)
    expect(leapDays).toHaveLength(29)
    expect(leapDays[leapDays.length - 1].iso).toBe('2024-02-29')

    const plain = monthMatrix(2026, 2)
    const plainDays = plain.weeks.flat().filter((c) => c.inMonth)
    expect(plainDays).toHaveLength(28)
    expect(plainDays[plainDays.length - 1].iso).toBe('2026-02-28')
  })

  it('crosses the new year without losing or duplicating a day', () => {
    const dec = monthMatrix(2026, 12)
    const jan = monthMatrix(2027, 1)
    expect(dec.weeks.flat().filter((c) => c.inMonth)).toHaveLength(31)
    // The last in-month day of December and the first of January are adjacent.
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(jan.weeks.flat().find((c) => c.inMonth)!.iso).toBe('2027-01-01')
  })

  it('keeps a stable 6 rows by default and the natural count when asked', () => {
    // February 2026 starts on a Sunday and needs 5 natural rows.
    expect(monthMatrix(2026, 2).weeks).toHaveLength(6)
    expect(monthMatrix(2026, 2, { fixedWeeks: false }).weeks).toHaveLength(5)
    // Every month is 6 rows under the default, which is what stops the grid
    // changing height as you page through months.
    for (let month = 1; month <= 12; month++) {
      expect(monthMatrix(2026, month).weeks).toHaveLength(6)
    }
  })

  it('respects a Sunday-first week when asked', () => {
    const m = monthMatrix(2026, 11, { weekStartsOn: 0 })
    expect(isoWeekday(m.start)).toBe(0)
    expect(m.start).toBe('2026-11-01') // the 1st IS a Sunday
    expect(m.weeks[0][0].inMonth).toBe(true)
  })

  it('emits contiguous days with no gaps across the whole grid', () => {
    const cells = monthMatrix(2026, 11).weeks.flat()
    for (let i = 1; i < cells.length; i++) {
      expect(cells[i].iso).toBe(addDays(cells[i - 1].iso, 1))
    }
  })

  it('flags weekends', () => {
    const m = monthMatrix(2026, 11)
    const cells = m.weeks.flat()
    expect(cells.filter((c) => c.isWeekend)).toHaveLength(12) // 6 rows × Sat+Sun
    expect(m.weeks[0][5].isWeekend).toBe(true) // Saturday
    expect(m.weeks[0][6].isWeekend).toBe(true) // Sunday
    expect(m.weeks[0][0].isWeekend).toBe(false) // Monday
  })
})

describe('placeSpans', () => {
  const nov = monthMatrix(2026, 11) // grid 2026-10-26 → 2026-12-06

  it('places a single-day event as a one-column segment on its own day', () => {
    const layout = placeSpans([ev(1, '2026-11-11')], nov)
    const week = layout.find((w) => w.segments.length > 0)!
    expect(week.week).toBe(2) // 9–15 Nov
    expect(sig(week.segments)).toEqual(['1@0:2-2']) // Wednesday
    expect(week.segments[0].length).toBe(1)
    expect(week.segments[0].isMultiDay).toBe(false)
    expect(week.segments[0].continuesBefore).toBe(false)
    expect(week.segments[0].continuesAfter).toBe(false)
  })

  it('draws a multi-day congress as one bar when it fits inside a week', () => {
    // 10–13 Nov 2026 is Tue–Fri.
    const layout = placeSpans([ev(1, '2026-11-10', '2026-11-13')], nov)
    const week = layout[2]
    expect(sig(week.segments)).toEqual(['1@0:1-4'])
    expect(week.segments[0].length).toBe(4)
    expect(week.segments[0].isMultiDay).toBe(true)
    expect(week.segments[0].continuesAfter).toBe(false)
  })

  it('clips a span across a week boundary into two segments with continuation flags', () => {
    // 13–17 Nov 2026: Fri–Tue, so it straddles the Sun/Mon row break.
    const layout = placeSpans([ev(1, '2026-11-13', '2026-11-17')], nov)
    const parts = layout.filter((w) => w.segments.length > 0)
    expect(parts).toHaveLength(2)

    expect(sig(parts[0].segments)).toEqual(['1@0:4-6']) // Fri–Sun
    expect(parts[0].segments[0].continuesBefore).toBe(false)
    expect(parts[0].segments[0].continuesAfter).toBe(true)

    expect(sig(parts[1].segments)).toEqual(['1@0:0-1']) // Mon–Tue
    expect(parts[1].segments[0].continuesBefore).toBe(true)
    expect(parts[1].segments[0].continuesAfter).toBe(false)
    // Both halves know they are part of a multi-day event.
    expect(parts.every((p) => p.segments[0].isMultiDay)).toBe(true)
  })

  it('clips a span that overruns the grid at both ends', () => {
    // A year-long course swallowing the whole November grid.
    const layout = placeSpans([ev(1, '2026-01-01', '2027-12-31')], nov)
    expect(layout).toHaveLength(6)
    for (const week of layout) {
      expect(sig(week.segments)).toEqual(['1@0:0-6'])
      expect(week.segments[0].continuesBefore).toBe(true)
      expect(week.segments[0].continuesAfter).toBe(true)
    }
  })

  it('stacks overlapping events into separate lanes and reuses a freed lane', () => {
    const layout = placeSpans(
      [
        ev(1, '2026-11-09', '2026-11-11'), // Mon–Wed
        ev(2, '2026-11-10', '2026-11-12'), // Tue–Thu, overlaps 1
        ev(3, '2026-11-13'), // Fri — lane 0 is free again by then
      ],
      nov
    )
    expect(sig(layout[2].segments)).toEqual(['1@0:0-2', '2@1:1-3', '3@0:4-4'])
    expect(layout[2].laneCount).toBe(2)
  })

  it('orders by start then by longest span, so a long congress takes the top lane', () => {
    const layout = placeSpans(
      [
        ev(7, '2026-11-09'), // same start, one day
        ev(3, '2026-11-09', '2026-11-13'), // same start, five days
      ],
      nov
    )
    // The long one wins lane 0 regardless of input order or id.
    expect(sig(layout[2].segments)).toEqual(['3@0:0-4', '7@1:0-0'])
  })

  it('is deterministic for identical spans, breaking ties by id', () => {
    const input = [ev(9, '2026-11-11'), ev(2, '2026-11-11'), ev(5, '2026-11-11')]
    const a = placeSpans(input, nov)
    const b = placeSpans([...input].reverse(), nov)
    expect(sig(a[2].segments)).toEqual(['2@0:2-2', '5@1:2-2', '9@2:2-2'])
    expect(sig(b[2].segments)).toEqual(sig(a[2].segments))
  })

  it('splits lanes past maxLanes into `hidden` with per-day counts, never dropping them', () => {
    const layout = placeSpans(
      [ev(1, '2026-11-11'), ev(2, '2026-11-11'), ev(3, '2026-11-11'), ev(4, '2026-11-11')],
      nov,
      { maxLanes: 2 }
    )
    const week = layout[2]
    expect(sig(week.segments)).toEqual(['1@0:2-2', '2@1:2-2'])
    expect(week.hidden.map((s) => s.event.id)).toEqual([3, 4])
    expect(week.laneCount).toBe(4) // what it WOULD need
    expect(week.hiddenCountByDay['2026-11-11']).toBe(2)
    expect(week.segments.length + week.hidden.length).toBe(4)
  })

  it('counts a hidden multi-day bar against every day it covers', () => {
    const layout = placeSpans(
      [ev(1, '2026-11-09', '2026-11-13'), ev(2, '2026-11-09', '2026-11-13'), ev(3, '2026-11-10', '2026-11-11')],
      nov,
      { maxLanes: 2 }
    )
    const week = layout[2]
    expect(week.hidden.map((s) => s.event.id)).toEqual([3])
    expect(week.hiddenCountByDay['2026-11-10']).toBe(1)
    expect(week.hiddenCountByDay['2026-11-11']).toBe(1)
    expect(week.hiddenCountByDay['2026-11-12']).toBeUndefined()
  })

  it('places events landing on the grid’s padding days from adjacent months', () => {
    // 28 Oct and 2 Dec 2026 both appear on the November grid as muted cells.
    const layout = placeSpans([ev(1, '2026-10-28'), ev(2, '2026-12-02')], nov)
    expect(sig(layout[0].segments)).toEqual(['1@0:2-2'])
    expect(sig(layout[5].segments)).toEqual(['2@0:2-2'])
  })

  it('ignores events with no date, a malformed date, or no overlap with the grid', () => {
    const layout = placeSpans(
      [ev(1, null), ev(2, '09/11/2026'), ev(3, '2026-02-30'), ev(4, '2027-05-01'), ev(5, '2026-08-01', '2026-08-04')],
      nov
    )
    expect(layout.every((w) => w.segments.length === 0 && w.hidden.length === 0)).toBe(true)
  })

  it('collapses a backwards or missing end date to a single day rather than drawing in reverse', () => {
    const layout = placeSpans(
      [ev(1, '2026-11-11', '2026-11-04'), ev(2, '2026-11-12', null), ev(3, '2026-11-13', 'rubbish')],
      nov
    )
    // Each collapses to its own single day (Wed/Thu/Fri), so they do not
    // overlap and all three share lane 0 — the point being that none of them
    // spills backwards over the days before it.
    expect(sig(layout[2].segments)).toEqual(['1@0:2-2', '2@0:3-3', '3@0:4-4'])
    expect(layout[2].segments.every((s) => s.length === 1 && !s.isMultiDay)).toBe(true)
    expect(layout[2].laneCount).toBe(1)
  })

  it('returns one layout per week row even when nothing is placed', () => {
    const layout = placeSpans([], nov)
    expect(layout).toHaveLength(6)
    expect(layout.map((w) => w.week)).toEqual([0, 1, 2, 3, 4, 5])
    expect(layout.every((w) => w.laneCount === 0)).toBe(true)
  })

  it('honours a Sunday-first grid when assigning columns', () => {
    const sunFirst = monthMatrix(2026, 11, { weekStartsOn: 0 })
    const layout = placeSpans([ev(1, '2026-11-09')], sunFirst) // a Monday
    const week = layout.find((w) => w.segments.length > 0)!
    expect(week.segments[0].startCol).toBe(1) // Monday is column 1 when Sunday leads
  })
})

describe('deadlinesByDay', () => {
  it('buckets abstract deadlines inside the range and drops the rest', () => {
    const map = deadlinesByDay(
      [
        { id: 1, abstractDeadline: '2026-11-11' },
        { id: 2, abstractDeadline: '2026-11-11' },
        { id: 3, abstractDeadline: '2026-12-25' }, // outside the grid
        { id: 4, abstractDeadline: null },
        { id: 5, abstractDeadline: 'soon' },
      ],
      { start: '2026-10-26', end: '2026-12-06' }
    )
    expect(Object.keys(map)).toEqual(['2026-11-11'])
    expect(map['2026-11-11'].map((e) => e.id)).toEqual([1, 2])
  })

  it('includes deadlines exactly on the range edges', () => {
    const map = deadlinesByDay(
      [{ id: 1, abstractDeadline: '2026-10-26' }, { id: 2, abstractDeadline: '2026-12-06' }],
      { start: '2026-10-26', end: '2026-12-06' }
    )
    expect(Object.keys(map).sort()).toEqual(['2026-10-26', '2026-12-06'])
  })
})

describe('eventsOnDay', () => {
  it('counts a multi-day event on every day it runs, not just its first', () => {
    const events = [ev(1, '2026-11-10', '2026-11-13'), ev(2, '2026-11-12'), ev(3, '2026-11-20'), ev(4, null)]
    expect(eventsOnDay(events, '2026-11-10').map((e) => e.id)).toEqual([1])
    expect(eventsOnDay(events, '2026-11-12').map((e) => e.id)).toEqual([1, 2])
    expect(eventsOnDay(events, '2026-11-13').map((e) => e.id)).toEqual([1]) // inclusive end
    expect(eventsOnDay(events, '2026-11-14')).toEqual([])
  })

  it('never returns an undated event', () => {
    expect(eventsOnDay([ev(1, null), ev(2, 'nope')], '2026-11-11')).toEqual([])
  })
})

describe('upcomingDeadlines', () => {
  const events = [
    { id: 1, abstractDeadline: '2026-10-20' },
    { id: 2, abstractDeadline: '2026-10-03' }, // today — still open
    { id: 3, abstractDeadline: '2026-10-02' }, // yesterday — closed
    { id: 4, abstractDeadline: '2026-12-02' }, // day 60 exactly
    { id: 5, abstractDeadline: '2026-12-03' }, // day 61 — out
    { id: 6, abstractDeadline: null },
    { id: 7, abstractDeadline: 'whenever' },
  ]

  it('returns open deadlines inside the window, soonest first', () => {
    expect(upcomingDeadlines(events, { from: '2026-10-03' }).map((e) => e.id)).toEqual([2, 1, 4])
  })

  it('includes the closing day itself and the last day of the window', () => {
    const ids = upcomingDeadlines(events, { from: '2026-10-03', days: 60 }).map((e) => e.id)
    expect(ids).toContain(2) // closes today
    expect(ids).toContain(4) // exactly 60 days out
    expect(ids).not.toContain(5) // one day past the window
    expect(ids).not.toContain(3) // already closed
  })

  it('respects a shorter window and breaks ties by id', () => {
    expect(upcomingDeadlines(events, { from: '2026-10-03', days: 7 }).map((e) => e.id)).toEqual([2])
    const sameDay = [
      { id: 9, abstractDeadline: '2026-10-10' },
      { id: 4, abstractDeadline: '2026-10-10' },
    ]
    expect(upcomingDeadlines(sameDay, { from: '2026-10-03' }).map((e) => e.id)).toEqual([4, 9])
  })
})

describe('deadlineCountdown', () => {
  it('counts down to the closing day and reports closure after it', () => {
    expect(deadlineCountdown('2026-10-03', '2026-10-03')).toBe('0 days left')
    expect(deadlineCountdown('2026-10-04', '2026-10-03')).toBe('1 day left')
    expect(deadlineCountdown('2026-10-13', '2026-10-03')).toBe('10 days left')
    expect(deadlineCountdown('2026-10-02', '2026-10-03')).toBe('closed yesterday')
    expect(deadlineCountdown('2026-09-28', '2026-10-03')).toBe('closed 5 days ago')
  })

  it('counts whole days across a month boundary and a DST weekend', () => {
    expect(deadlineCountdown('2026-11-01', '2026-10-25')).toBe('7 days left')
    expect(deadlineCountdown('2027-01-01', '2026-12-31')).toBe('1 day left')
  })
})

describe('shortDateLabel', () => {
  it('renders a weekday, day and short month', () => {
    expect(shortDateLabel('2026-10-03', 'en-GB')).toMatch(/^Sat\b.*3.*Oct/)
    expect(shortDateLabel('2026-12-25', 'en-GB')).toMatch(/Dec/)
  })

  it('returns the raw string rather than throwing on a malformed date', () => {
    expect(shortDateLabel('nope', 'en-GB')).toBe('nope')
  })
})

describe('eventsInMonth', () => {
  it('counts anything overlapping the month, including spans that only clip its edges', () => {
    const ids = eventsInMonth(
      [
        ev(1, '2026-11-11'), // inside
        ev(2, '2026-10-30', '2026-11-02'), // overlaps the start
        ev(3, '2026-11-28', '2026-12-04'), // overlaps the end
        ev(4, '2026-10-01', '2026-10-20'), // entirely before
        ev(5, '2026-12-10'), // entirely after
        ev(6, null), // undated
        ev(7, '2026-01-01', '2027-01-01'), // swallows the month
      ],
      2026,
      11
    ).map((e) => e.id)
    expect(ids).toEqual([1, 2, 3, 7])
  })
})

describe('groupByMonth', () => {
  it('groups dated events by start month in chronological order and separates undated ones', () => {
    const { groups, undated } = groupByMonth([
      ev(3, '2026-12-02'),
      ev(1, '2026-11-11'),
      ev(4, null),
      ev(2, '2026-11-20'),
      ev(5, '2027-01-05'),
    ])
    expect(groups.map((g) => g.key)).toEqual(['2026-11', '2026-12', '2027-01'])
    expect(groups[0].events.map((e) => e.id)).toEqual([1, 2])
    expect(groups[0]).toMatchObject({ year: 2026, month: 11 })
    expect(undated.map((e) => e.id)).toEqual([4])
  })

  it('with `from`, keeps an in-progress event but drops finished ones', () => {
    const { groups } = groupByMonth(
      [
        ev(1, '2026-11-01', '2026-11-30'), // started, still running
        ev(2, '2026-10-01', '2026-10-05'), // over
        ev(3, '2026-12-01'), // future
      ],
      { from: '2026-11-15' }
    )
    expect(groups.flatMap((g) => g.events).map((e) => e.id)).toEqual([1, 3])
  })

  it('keeps undated events regardless of `from`', () => {
    const { groups, undated } = groupByMonth([ev(1, null), ev(2, '2020-01-01')], { from: '2026-11-15' })
    expect(groups).toHaveLength(0)
    expect(undated.map((e) => e.id)).toEqual([1])
  })
})

describe('labels', () => {
  it('returns seven weekday labels starting at the requested day', () => {
    const mon = weekdayLabels(1, 'en-GB')
    expect(mon).toHaveLength(7)
    expect(mon[0]).toMatch(/^Mon/)
    expect(mon[6]).toMatch(/^Sun/)
    const sun = weekdayLabels(0, 'en-GB')
    expect(sun[0]).toMatch(/^Sun/)
    expect(sun[1]).toMatch(/^Mon/)
  })

  it('follows the locale for label text while the grid order stays Monday-first', () => {
    const fr = weekdayLabels(1, 'fr-FR')
    expect(fr[0].toLowerCase()).toMatch(/^lun/)
    expect(fr).toHaveLength(7)
  })
})
