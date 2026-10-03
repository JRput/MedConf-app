'use client'

import { useMemo } from 'react'
import { CalendarOff } from 'lucide-react'
import type { DirectoryEvent } from '@/lib/directory'
import { groupByMonth, monthLabel, todayIso } from '@/lib/calendar'
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
  const { groups, undated } = useMemo(() => groupByMonth(events, { from: todayIso() }), [events])

  if (loading) {
    return <EventRowList events={[]} savedIds={savedIds} loading skeletonCount={5} />
  }

  if (groups.length === 0 && undated.length === 0) {
    return <>{emptyState ?? null}</>
  }

  return (
    <div className="space-y-8">
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
