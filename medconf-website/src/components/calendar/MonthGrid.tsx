'use client'

import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import type { DirectoryEvent } from '@/lib/directory'
import {
  deadlinesByDay,
  longDateLabel,
  monthMatrix,
  placeSpans,
  todayIso,
  weekdayLabels,
  type DayCell,
  type WeekLayout,
} from '@/lib/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { DeadlineMarker } from './DeadlineMarker'
import { EventChip, EventChipRow } from './EventChip'
import { useLocale } from './useLocale'

/**
 * The month grid. 7 columns, Monday-first, one row per week.
 *
 * LAYOUT. Day cells are a plain CSS grid; events are an absolutely positioned
 * overlay on top of each row, with `left`/`width` as percentages of the row.
 * That is what makes a 4-day congress one continuous bar rather than four
 * chips that happen to sit next to each other — and percentages mean it stays
 * aligned at any container width without measuring anything in JS.
 *
 * Lane height is fixed, so a row's height is arithmetic rather than content —
 * `header + lanesUsed × lane + overflow`. Every row in a month is therefore
 * identical and nothing shifts as the grid scrolls, while `lanesUsed` adapts
 * to the busiest week so a quiet month is not padded out with lanes nothing
 * uses. The row COUNT is fixed at 6 (see monthMatrix's `fixedWeeks` note),
 * which is what keeps paging between months from feeling like a jump.
 *
 * `compact` is the dashboard's mini month: dots instead of chips, no overflow
 * affordance, not interactive. Same engine, same month maths — so the mini
 * grid can never disagree with the real one.
 */

/** Row geometry, in px. Shared with the row-height arithmetic below. */
const LANE_H = 20
const LANE_GAP = 2
const HEADER_H = 26
const OVERFLOW_H = 18
/** Reserved under the day number for the abstract-deadline marker. */
const DEADLINE_H = 18

export function MonthGrid({
  year,
  month,
  events,
  selectedId,
  onSelect,
  onSelectDay,
  onSelectDeadline,
  maxLanes = 3,
  compact = false,
  className,
}: {
  year: number
  /** 1–12 */
  month: number
  events: DirectoryEvent[]
  selectedId?: number | null
  onSelect?: (event: DirectoryEvent) => void
  /** Clicking empty space in a day cell — used by the mobile day list. */
  onSelectDay?: (iso: string) => void
  /** Clicking a deadline marker — opens the panel with the deadline called out. */
  onSelectDeadline?: (event: DirectoryEvent) => void
  /** Lanes shown before events spill into "+N more". */
  maxLanes?: number
  /** Dashboard mini-grid mode: dots only, non-interactive. */
  compact?: boolean
  className?: string
}) {
  const locale = useLocale()
  const today = todayIso()

  const matrix = useMemo(() => monthMatrix(year, month, { weekStartsOn: 1 }), [year, month])
  const layout = useMemo(
    () => placeSpans(events, matrix, { maxLanes: compact ? 0 : maxLanes }),
    [events, matrix, maxLanes, compact]
  )
  const deadlines = useMemo(() => deadlinesByDay(events, matrix), [events, matrix])
  const labels = useMemo(() => weekdayLabels(1, locale, compact ? 'narrow' : 'short'), [locale, compact])

  // In compact mode every event is "hidden" (maxLanes 0), which is exactly the
  // set we want to render as dots.
  const dotsByDay = useMemo(() => {
    if (!compact) return {}
    const out: Record<string, DirectoryEvent[]> = {}
    for (const week of layout) {
      for (const seg of week.hidden) {
        for (let c = seg.startCol; c <= seg.endCol; c++) {
          const iso = matrix.weeks[week.week][c].iso
          const list = (out[iso] ??= [])
          if (!list.some((e) => e.id === seg.event.id)) list.push(seg.event)
        }
      }
    }
    return out
  }, [compact, layout, matrix])

  // Size rows to what this month actually needs rather than always reserving
  // `maxLanes` + an overflow strip. A quiet month was paying ~60px of dead
  // space per row for lanes nothing ever used. Every row in a given month is
  // still identical, so nothing shifts as you scroll — only the step between
  // one month and the next changes, which is the cheaper of the two evils.
  const lanesUsed = Math.max(1, Math.min(maxLanes, Math.max(1, ...layout.map((w) => w.laneCount))))
  const hasOverflow = layout.some((w) => Object.keys(w.hiddenCountByDay).length > 0)
  // The deadline strip is reserved for the whole month as soon as ANY day in
  // view carries one, rather than per row. The chip overlay is positioned in
  // JS while the marker's labelled/icon-only form is chosen by a CSS container
  // query, so JS cannot know how tall the marker renders — reserving one fixed
  // strip is what keeps the two from ever overlapping.
  const deadlineH = !compact && Object.keys(deadlines).length > 0 ? DEADLINE_H : 0
  const headerH = HEADER_H + deadlineH
  const rowHeight = compact
    ? 34
    : headerH + lanesUsed * (LANE_H + LANE_GAP) + (hasOverflow ? OVERFLOW_H : 2)

  return (
    // `@container`: the deadline marker shows its "Abstracts: <title>" label
    // only where a day cell is wide enough for it, which depends on how wide
    // the GRID is (side panel open or not, phone or desktop) — not on the
    // viewport. Same mechanism EventRow uses; see globals.css's --container-row-*.
    <div className={cn('@container overflow-hidden rounded-lg border border-border bg-surface', className)}>
      {/* Weekday header */}
      <div className="grid grid-cols-7 border-b border-border bg-surface-muted">
        {labels.map((label, i) => (
          <div
            key={i}
            className={cn(
              'px-2 py-1.5 text-center type-mono-label',
              i >= 5 ? 'text-fg-subtle' : 'text-fg-muted',
              compact && 'px-0 py-1'
            )}
          >
            {label}
          </div>
        ))}
      </div>

      {matrix.weeks.map((week, w) => (
        <WeekRow
          key={week[0].iso}
          week={week}
          layout={layout[w]}
          locale={locale}
          today={today}
          deadlines={deadlines}
          dots={dotsByDay}
          selectedId={selectedId}
          onSelect={onSelect}
          onSelectDay={onSelectDay}
          onSelectDeadline={onSelectDeadline}
          headerH={headerH}
          lanesUsed={lanesUsed}
          compact={compact}
          height={rowHeight}
          isLast={w === matrix.weeks.length - 1}
        />
      ))}
    </div>
  )
}

function WeekRow({
  week,
  layout,
  locale,
  today,
  deadlines,
  dots,
  selectedId,
  onSelect,
  onSelectDay,
  onSelectDeadline,
  headerH,
  lanesUsed,
  compact,
  height,
  isLast,
}: {
  week: DayCell[]
  layout: WeekLayout<DirectoryEvent>
  locale: string
  today: string
  deadlines: Record<string, DirectoryEvent[]>
  dots: Record<string, DirectoryEvent[]>
  selectedId?: number | null
  onSelect?: (event: DirectoryEvent) => void
  onSelectDay?: (iso: string) => void
  onSelectDeadline?: (event: DirectoryEvent) => void
  headerH: number
  lanesUsed: number
  compact: boolean
  height: number
  isLast: boolean
}) {
  return (
    <div
      className={cn('relative grid grid-cols-7', !isLast && 'border-b border-border-subtle')}
      style={{ height }}
    >
      {week.map((cell, i) => (
        <DayCellBox
          key={cell.iso}
          cell={cell}
          isToday={cell.iso === today}
          deadlineEvents={deadlines[cell.iso]}
          locale={locale}
          onSelectDeadline={onSelectDeadline}
          dots={dots[cell.iso]}
          onSelectDay={onSelectDay}
          compact={compact}
          isLastCol={i === 6}
        />
      ))}

      {/* Event overlay. `pointer-events-none` so the empty parts of a row stay
          clickable as day cells; each chip re-enables them for itself. */}
      {!compact && (
        <div className="pointer-events-none absolute inset-x-0" style={{ top: headerH, bottom: 0 }}>
          {layout.segments.map((seg) => (
            <div
              key={`${seg.event.id}-${seg.week}`}
              className="pointer-events-auto absolute px-px"
              style={{
                left: `${(seg.startCol / 7) * 100}%`,
                width: `${(seg.length / 7) * 100}%`,
                top: seg.lane * (LANE_H + LANE_GAP),
                height: LANE_H,
              }}
            >
              <EventChip segment={seg} selected={selectedId === seg.event.id} onSelect={onSelect} />
            </div>
          ))}

          {/* "+N more", one per day that has anything beyond the last lane. */}
          {Object.keys(layout.hiddenCountByDay).length > 0 && (
            <div
              className="absolute inset-x-0 grid grid-cols-7"
              style={{ top: lanesUsed * (LANE_H + LANE_GAP), height: OVERFLOW_H }}
            >
              {week.map((cell, col) => {
                const count = layout.hiddenCountByDay[cell.iso] ?? 0
                if (count === 0) return <div key={cell.iso} />
                return (
                  <OverflowButton
                    key={cell.iso}
                    label={longDateLabel(cell.iso, locale)}
                    count={count}
                    events={layout.hidden.filter((s) => s.startCol <= col && s.endCol >= col).map((s) => s.event)}
                    selectedId={selectedId}
                    onSelect={onSelect}
                  />
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function DayCellBox({
  cell,
  isToday,
  deadlineEvents,
  locale,
  onSelectDeadline,
  dots,
  onSelectDay,
  compact,
  isLastCol,
}: {
  cell: DayCell
  isToday: boolean
  deadlineEvents?: DirectoryEvent[]
  locale: string
  onSelectDeadline?: (event: DirectoryEvent) => void
  dots?: DirectoryEvent[]
  onSelectDay?: (iso: string) => void
  compact: boolean
  isLastCol: boolean
}) {
  const content = (
    <>
      <div className={cn('flex items-center justify-between gap-1', compact ? 'justify-center' : '')}>
        <span
          className={cn(
            'type-numeric inline-flex items-center justify-center text-[0.75rem] leading-none tabular-nums',
            compact ? 'size-5 text-[0.6875rem]' : 'size-[1.375rem]',
            cell.inMonth ? 'text-fg' : 'text-fg-subtle',
            // The today ring, not a filled today chip — a filled block competes
            // with the event chips for the eye at exactly the moment you are
            // trying to read them.
            isToday && 'rounded-full ring-1 ring-brand font-semibold text-brand-text'
          )}
        >
          {cell.day}
        </span>
      </div>

      {/* The deadline strip. Its height is reserved for every cell in a month
          that has any deadline, so the rows stay aligned whether or not this
          particular day carries one. */}
      {!compact && deadlineEvents && deadlineEvents.length > 0 && (
        <div className="mt-0.5">
          <DeadlineMarker iso={cell.iso} events={deadlineEvents} locale={locale} onSelect={onSelectDeadline} />
        </div>
      )}

      {compact && dots && dots.length > 0 && (
        <div className="mt-0.5 flex items-center justify-center gap-0.5">
          {dots.slice(0, 3).map((e) => (
            <span
              key={e.id}
              className={cn(
                'size-1 rounded-full',
                e.eventType === 'course'
                  ? 'bg-type-course-text'
                  : e.eventType === 'workshop'
                    ? 'bg-type-workshop-text'
                    : 'bg-type-conference-text'
              )}
            />
          ))}
        </div>
      )}
    </>
  )

  const base = cn(
    'px-1.5 pt-1',
    !isLastCol && 'border-r border-border-subtle',
    // Days outside the month sit back without disappearing — they still carry
    // real events from the neighbouring months.
    !cell.inMonth && 'bg-surface-muted/50',
    cell.inMonth && cell.isWeekend && 'bg-surface-muted/30'
  )

  if (compact || !onSelectDay) {
    return <div className={base}>{content}</div>
  }

  return (
    <button
      type="button"
      onClick={() => onSelectDay(cell.iso)}
      className={cn(
        base,
        'text-left transition-colors duration-150 hover:bg-surface-hover',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset focus-visible:outline-none'
      )}
    >
      {content}
    </button>
  )
}

function OverflowButton({
  label,
  count,
  events,
  selectedId,
  onSelect,
}: {
  /** Human-readable day, e.g. "Wednesday 11 November 2026" — for the aria-label and popover heading. */
  label: string
  count: number
  events: DirectoryEvent[]
  selectedId?: number | null
  onSelect?: (event: DirectoryEvent) => void
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            // `pointer-events-auto` is load-bearing: the whole overlay is
            // pointer-events-none so empty parts of a row stay clickable as
            // day cells, which means every interactive thing inside it has to
            // opt back in. Without this the popover can never open — the day
            // cell underneath swallows the click.
            // `w-fit`, not the full column: a full-width hover bar reads as a
            // selected day rather than a small "there is more here" control.
            'pointer-events-auto mx-px flex h-full w-fit items-center rounded-sm px-1.5 text-left type-mono-label',
            'text-fg-muted transition-colors duration-150 hover:bg-surface-active hover:text-fg',
            'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
          )}
          aria-label={`${count} more event${count === 1 ? '' : 's'} on ${label}`}
        >
          +{count}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-2">
        <p className="px-1 pb-1.5 type-mono-label text-fg-subtle">{label}</p>
        <div className="space-y-1">
          {events.map((event) => (
            <EventChipRow key={event.id} event={event} selected={selectedId === event.id} onSelect={onSelect} />
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
