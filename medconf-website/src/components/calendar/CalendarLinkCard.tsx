'use client'

import Link from 'next/link'
import { ArrowUpRight } from 'lucide-react'
import { useMemo } from 'react'
import { eventsInMonth, monthLabel, todayIso } from '@/lib/calendar'
import type { DirectoryEvent } from '@/lib/directory'
import { MonthGrid } from './MonthGrid'
import { useLocale } from './useLocale'

/**
 * The dashboard's link into /calendar — a real mini month of the user's saved
 * events rather than a "coming soon" placeholder.
 *
 * It renders MonthGrid in `compact` mode, so the dots are produced by the same
 * span layout as the full grid. A second, simpler mini-grid implementation
 * here would be the kind of thing that quietly disagrees with the real one
 * about which week a congress falls in.
 */
export function CalendarLinkCard({ events }: { events: DirectoryEvent[] }) {
  const locale = useLocale()
  const today = todayIso()
  const year = Number(today.slice(0, 4))
  const month = Number(today.slice(5, 7))

  const count = useMemo(() => eventsInMonth(events, year, month).length, [events, year, month])

  return (
    <Link
      href="/calendar"
      className="group flex flex-col gap-4 rounded-lg border border-border bg-surface p-4 transition-colors duration-150 hover:border-border-strong sm:flex-row sm:items-center sm:gap-5"
    >
      <div className="w-full shrink-0 sm:w-[232px]">
        <MonthGrid year={year} month={month} events={events} compact />
      </div>

      <div className="min-w-0 flex-1">
        <p className="type-mono-label text-fg-subtle">{monthLabel(year, month, locale)}</p>
        <p className="mt-1.5 type-h3 text-fg-strong transition-colors duration-150 group-hover:text-brand-text">
          Your calendar
        </p>
        <p className="mt-1 type-small text-fg-muted">
          {count === 0
            ? 'Nothing saved this month. See the months ahead on the grid.'
            : `${count} saved event${count === 1 ? '' : 's'} this month, with multi-day congresses and abstract deadlines marked.`}
        </p>
        <span className="mt-2 inline-flex items-center gap-1 type-small font-medium text-brand-text">
          Open calendar
          <ArrowUpRight className="size-4 transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
        </span>
      </div>
    </Link>
  )
}
