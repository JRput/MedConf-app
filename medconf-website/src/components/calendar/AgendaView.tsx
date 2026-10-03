'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { CalendarOff, FileClock } from 'lucide-react'
import type { DirectoryEvent } from '@/lib/directory'
import {
  deadlineCountdown,
  groupByMonth,
  monthLabel,
  shortDateLabel,
  todayIso,
  upcomingDeadlines,
} from '@/lib/calendar'
import { EventRowList } from '@/components/account/EventRowList'
import { useLocale } from './useLocale'

/**
 * The list half of the view toggle: upcoming saved events grouped by month,
 * rendered with the same EventRow/EventCardCompact pair as /saved and the
 * dashboard. Reusing EventRowList rather than styling rows again here is what
 * keeps a saved event looking identical in all four places it appears.
 *
 * Undated saves get their own group at the end instead of being dropped — a
 * saved event with no published date is still something the user chose to
 * track, and it cannot honestly be placed on the grid.
 */
export function AgendaView({
  events,
  savedIds,
  onToggleSave,
  loading = false,
  emptyState,
}: {
  events: DirectoryEvent[]
  savedIds: Set<number>
  onToggleSave?: (id: number, next: boolean) => void
  loading?: boolean
  emptyState?: React.ReactNode
}) {
  const locale = useLocale()
  const today = todayIso()
  const { groups, undated } = useMemo(() => groupByMonth(events, { from: today }), [events, today])
  const deadlines = useMemo(() => upcomingDeadlines(events, { from: today, days: 60 }), [events, today])

  if (loading) {
    return <EventRowList events={[]} savedIds={savedIds} loading skeletonCount={5} />
  }

  if (groups.length === 0 && undated.length === 0 && deadlines.length === 0) {
    return <>{emptyState ?? null}</>
  }

  return (
    <div className="space-y-8">
      {/* Deadlines lead the agenda. A submission date is the one thing on this
          page that expires — an event you miss by a week is still findable
          next year, an abstract deadline is not. */}
      {deadlines.length > 0 && (
        <section>
          <div className="mb-2.5 flex items-baseline justify-between gap-3">
            <h2 className="flex items-center gap-2 type-h3 text-fg-strong">
              <FileClock className="size-4 text-warn-text" strokeWidth={2} aria-hidden />
              Upcoming deadlines
            </h2>
            <span className="type-mono-label text-fg-subtle">Next 60 days</span>
          </div>
          <ul className="divide-y divide-border-subtle overflow-hidden rounded-lg border border-border bg-surface">
            {deadlines.map((event) => (
              <li key={event.id}>
                <Link
                  href={event.href}
                  className="flex items-center gap-3 px-3 py-2.5 transition-colors duration-150 hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:outline-none"
                >
                  <span className="type-mono-label shrink-0 text-warn-text">
                    {shortDateLabel(event.abstractDeadline!, locale)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[0.875rem] font-medium text-fg-strong">
                    {event.name}
                  </span>
                  <span className="shrink-0 type-mono-label text-fg-subtle">
                    {deadlineCountdown(event.abstractDeadline!, today)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {groups.map((group) => (
        <section key={group.key}>
          <div className="mb-2.5 flex items-baseline justify-between gap-3">
            <h2 className="type-h3 text-fg-strong">{monthLabel(group.year, group.month, locale)}</h2>
            <span className="type-mono-label text-fg-subtle">
              {group.events.length} event{group.events.length === 1 ? '' : 's'}
            </span>
          </div>
          <EventRowList events={group.events} savedIds={savedIds} onToggleSave={onToggleSave} />
        </section>
      ))}

      {undated.length > 0 && (
        <section>
          <div className="mb-2.5 flex items-baseline justify-between gap-3">
            <h2 className="flex items-center gap-2 type-h3 text-fg-strong">
              <CalendarOff className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
              Undated
            </h2>
            <span className="type-mono-label text-fg-subtle">
              {undated.length} event{undated.length === 1 ? '' : 's'}
            </span>
          </div>
          <p className="mb-2.5 type-small text-fg-muted">
            Saved events whose organiser has not published a date yet. They are not on the month grid.
          </p>
          <EventRowList events={undated} savedIds={savedIds} onToggleSave={onToggleSave} />
        </section>
      )}
    </div>
  )
}
