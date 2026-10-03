'use client'

import { useMemo, useRef } from 'react'
import { ChevronLeft, ChevronRight, FileClock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DirectoryEvent } from '@/lib/directory'
import {
  addDays,
  columnOf,
  deadlinesByDay,
  eventsOnDay,
  longDateLabel,
  monthLabel,
  todayIso,
  weekdayLabels,
} from '@/lib/calendar'
import { EventCardCompact } from '@/components/domain/EventCardCompact'
import { useLocale } from './useLocale'

/**
 * The phone view. A month grid at 390px gives each day about 50px of width,
 * which is not enough for a readable event title — so phones get a 7-day
 * strip of dates with dot indicators and the selected day's events in full
 * underneath, which is the shape that actually answers "what have I got on?".
 *
 * The month grid is still reachable on a phone via the header's toggle; it is
 * just not the default.
 *
 * Swiping left/right moves a week. The handler is a plain touch delta rather
 * than a gesture library: one axis, one threshold, and a vertical-dominant
 * move is left alone so the page still scrolls.
 */
export function WeekStrip({
  /** Any date in the week to show. */
  anchor,
  events,
  savedIds,
  onToggleSave,
  onAnchorChange,
  className,
}: {
  anchor: string
  events: DirectoryEvent[]
  savedIds: Set<number>
  onToggleSave?: (id: number, next: boolean) => void
  onAnchorChange: (iso: string) => void
  className?: string
}) {
  const locale = useLocale()
  const today = todayIso()
  const touchStart = useRef<{ x: number; y: number } | null>(null)

  const weekStart = useMemo(() => addDays(anchor, -columnOf(anchor, 1)), [anchor])
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])
  const labels = useMemo(() => weekdayLabels(1, locale, 'narrow'), [locale])
  const deadlines = useMemo(() => deadlinesByDay(events, { start: days[0], end: days[6] }), [events, days])

  const dayEvents = useMemo(() => eventsOnDay(events, anchor), [events, anchor])
  const dayDeadlines = useMemo(
    () => events.filter((e) => e.abstractDeadline === anchor),
    [events, anchor]
  )

  /** The soonest day after `anchor` that has anything on it — the empty state's way out. */
  const nextDay = useMemo(() => {
    const starts = events
      .map((e) => e.startDate)
      .filter((d): d is string => Boolean(d) && (d as string) > anchor)
      .sort()
    return starts[0] ?? null
  }, [events, anchor])

  const onTouchEnd = (e: React.TouchEvent) => {
    const start = touchStart.current
    touchStart.current = null
    if (!start) return
    const dx = e.changedTouches[0].clientX - start.x
    const dy = e.changedTouches[0].clientY - start.y
    // Ignore a mostly-vertical move — that is the user scrolling the page.
    if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy)) return
    onAnchorChange(addDays(anchor, dx < 0 ? 7 : -7))
  }

  return (
    <div className={cn('space-y-4', className)}>
      <div
        className="rounded-lg border border-border bg-surface"
        onTouchStart={(e) => {
          touchStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }
        }}
        onTouchEnd={onTouchEnd}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border-subtle px-2 py-1.5">
          <StripNav direction="prev" onClick={() => onAnchorChange(addDays(anchor, -7))} />
          <span className="type-mono-label text-fg-muted">
            {weekRangeLabel(days[0], days[6], locale)}
          </span>
          <StripNav direction="next" onClick={() => onAnchorChange(addDays(anchor, 7))} />
        </div>

        <div className="grid grid-cols-7">
          {days.map((iso, i) => {
            const count = eventsOnDay(events, iso).length
            const hasDeadline = Boolean(deadlines[iso]?.length)
            const isSelected = iso === anchor
            const isToday = iso === today
            return (
              <button
                key={iso}
                type="button"
                onClick={() => onAnchorChange(iso)}
                aria-pressed={isSelected}
                aria-label={`${longDateLabel(iso, locale)} — ${count} event${count === 1 ? '' : 's'}`}
                className={cn(
                  // 44px minimum touch target, per the kit's touch rule.
                  'flex min-h-11 flex-col items-center gap-1 py-2',
                  'transition-colors duration-150',
                  'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset focus-visible:outline-none',
                  isSelected ? 'bg-brand-subtle' : 'hover:bg-surface-hover'
                )}
              >
                <span className={cn('type-mono-label', isSelected ? 'text-brand-text' : 'text-fg-subtle')}>
                  {labels[i]}
                </span>
                <span
                  className={cn(
                    'type-numeric inline-flex size-6 items-center justify-center text-[0.8125rem] leading-none',
                    isSelected ? 'font-semibold text-brand-text' : 'text-fg',
                    isToday && !isSelected && 'rounded-full ring-1 ring-brand font-semibold text-brand-text'
                  )}
                >
                  {Number(iso.slice(8, 10))}
                </span>
                <span className="flex h-1.5 items-center gap-0.5">
                  {count > 0 && (
                    <span className={cn('size-1.5 rounded-full', isSelected ? 'bg-brand' : 'bg-fg-muted')} />
                  )}
                  {hasDeadline && <span className="size-1.5 rounded-full bg-warn" />}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <h2 className="mb-2 type-h3 text-fg-strong">{longDateLabel(anchor, locale)}</h2>

        {dayDeadlines.length > 0 && (
          <div className="mb-2.5 flex items-start gap-2 rounded-md border border-warn-border bg-warn-subtle px-3 py-2">
            <FileClock className="mt-0.5 size-4 shrink-0 text-warn-text" strokeWidth={2} aria-hidden />
            <p className="type-small text-warn-text">
              Abstract deadline{dayDeadlines.length === 1 ? '' : 's'}:{' '}
              {dayDeadlines.map((e) => e.name).join(', ')}
            </p>
          </div>
        )}

        {dayEvents.length === 0 ? (
          // A bare "nothing here" on the day you happen to land on is a dead
          // end, and on a phone the way out is several swipes away — so the
          // empty state carries the jump to the next day that has something.
          <div className="rounded-lg border border-dashed border-border bg-surface-muted px-4 py-6 text-center">
            <p className="type-small text-fg-muted">Nothing saved on this day.</p>
            {nextDay && (
              <button
                type="button"
                onClick={() => onAnchorChange(nextDay)}
                className="mt-2 min-h-11 type-small font-medium text-brand-text hover:underline"
              >
                Next: {longDateLabel(nextDay, locale)}
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-2.5">
            {dayEvents.map((event) => (
              <EventCardCompact
                key={event.id}
                event={event}
                saved={savedIds.has(event.id)}
                onToggleSave={onToggleSave ? (next) => onToggleSave(event.id, next) : undefined}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function weekRangeLabel(start: string, end: string, locale: string): string {
  const startMonth = monthLabel(Number(start.slice(0, 4)), Number(start.slice(5, 7)), locale, { month: 'short' })
  const endMonth = monthLabel(Number(end.slice(0, 4)), Number(end.slice(5, 7)), locale, { month: 'short' })
  const d1 = Number(start.slice(8, 10))
  const d2 = Number(end.slice(8, 10))
  const year = end.slice(0, 4)
  return startMonth === endMonth ? `${d1}–${d2} ${endMonth} ${year}` : `${d1} ${startMonth} – ${d2} ${endMonth} ${year}`
}

function StripNav({ direction, onClick }: { direction: 'prev' | 'next'; onClick: () => void }) {
  const Icon = direction === 'prev' ? ChevronLeft : ChevronRight
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={direction === 'prev' ? 'Previous week' : 'Next week'}
      className={cn(
        'inline-flex size-11 items-center justify-center rounded-md text-fg-muted',
        'transition-colors duration-150 hover:bg-surface-hover hover:text-fg',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
      )}
    >
      <Icon className="size-4" strokeWidth={2} aria-hidden />
    </button>
  )
}
