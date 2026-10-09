'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { locationLine, type DirectoryEvent } from '@/lib/directory'
import { isOngoing } from '@/lib/format'
import { DateBlock } from './DateBlock'
import { EventTypeBadge } from './EventTypeBadge'
import { FormatBadge } from './FormatBadge'
import { PriceLabel } from './PriceLabel'
import { CpdLabel } from './CpdLabel'
import { SocietyChip } from './SocietyChip'
import { EventStatus } from './EventStatus'
import { SaveToggle } from './SaveToggle'

/**
 * The dense row — the directory's default unit from W2 onwards, rendered
 * whenever its container is at least `--container-row-sm` wide (see
 * ResultsList.tsx's `@container` wrapper; narrower than that gets
 * EventCardCompact instead).
 *
 * It responds to the width of its CONTAINER, not the viewport — the same
 * row markup sits in the wide directory content column, a narrower
 * dashboard card, and a tablet-width column with no sidebar, and those can
 * all be true at the same browser width depending on what wraps it. Below
 * that it has two layouts of its own, both declared here (one `hidden` at
 * a time via the `@row-md` container variant) rather than one grid whose
 * columns squeeze:
 *
 *   >= row-md (900px container): the original dense grid — date leaf,
 *     title + one meta line, price/status column on the right. Specialty
 *     and location are allowed to truncate here; there's room for them not
 *     to.
 *   row-sm..row-md (720-900px container, e.g. a tablet-width column with no
 *     sidebar, or a narrower dashboard card): date leaf + a 3-line stack —
 *     title; society · specialty; format · location · CPD · price · status.
 *     Letting that third line wrap is what fixed the real bug this
 *     responds to: at this width the grid version truncated the SOCIETY
 *     name ("Royal College of Ophthalmolog…") and wrapped "In person"
 *     mid-word, when the owner's explicit call is that the society must
 *     never truncate — only specialty/location may.
 *
 * Society never truncates in either layout (see SocietyChip's doc
 * comment) — it's `shrink-0`, so specialty/location give way to it instead.
 */
export function EventRow({
  event,
  saved = false,
  onToggleSave,
  societyCount,
  className,
}: {
  event: DirectoryEvent
  saved?: boolean
  onToggleSave?: (next: boolean) => void
  /** Upcoming-event count for event.society, when the caller has it (see SocietyChip). */
  societyCount?: number
  className?: string
}) {
  const place = locationLine(event)
  // On-demand rows reuse start_date as an access deadline, not a real start —
  // "ongoing" only applies to genuine start/end spans.
  const ongoing = !event.isOnDemand && isOngoing(event.startDate, event.endDate)

  return (
    <div
      className={cn(
        'group relative border-b border-border-subtle px-3 py-3 last:border-b-0',
        'transition-colors duration-150',
        'hover:bg-surface-hover',
        'has-[a:focus-visible]:bg-surface-hover has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring has-[a:focus-visible]:ring-inset',
        className
      )}
    >
      {/* ---- row-sm..row-md: 3-line stack, nothing truncates but specialty/location ---- */}
      <div className="flex gap-3 @row-md:hidden">
        <DateBlock startDate={event.startDate} endDate={event.endDate} ongoing={ongoing} />

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3
              className={cn(
                'line-clamp-2 text-[0.9375rem] font-medium leading-snug text-fg-strong',
                'transition-colors duration-150 group-hover:text-brand-text',
                event.isSoldOut && 'text-fg-muted'
              )}
            >
              {event.name}
            </h3>
            <SaveToggle saved={saved} onToggle={onToggleSave} label={event.name} className="-mt-1 -mr-1" />
          </div>

          {(event.society || event.specialty) && (
            <div className="mt-1 flex min-w-0 items-center gap-x-2 gap-y-1 text-[0.8125rem] text-fg-muted">
              {event.society && <SocietyChip name={event.society} count={societyCount} />}
              {event.specialty && (
                <>
                  {event.society && <Dot />}
                  <span className="min-w-0 truncate">{event.specialty}</span>
                </>
              )}
            </div>
          )}

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-fg-muted">
            <EventTypeBadge type={event.eventType} isFlagship={event.isFlagship} isOnDemand={event.isOnDemand} />
            {event.format && <FormatBadge format={event.format} />}
            {place && <span className="truncate">{place}</span>}
            <CpdLabel accredited={event.cpdAccredited} points={event.cpdPoints} />
            <PriceLabel min={event.priceMin} max={event.priceMax} currency={event.currency} href={event.organiserUrl} />
            <EventStatus event={event} />
          </div>
        </div>
      </div>

      {/* ---- row-md+: the original dense single-line grid, unchanged ---- */}
      <div className="hidden @row-md:grid @row-md:grid-cols-[3.5rem_minmax(0,1fr)_auto] @row-md:items-center @row-md:gap-x-4">
        <DateBlock startDate={event.startDate} endDate={event.endDate} ongoing={ongoing} />

        <div className="min-w-0">
          <h3
            className={cn(
              'truncate text-[0.9375rem] font-medium leading-snug text-fg-strong',
              'transition-colors duration-150 group-hover:text-brand-text',
              event.isSoldOut && 'text-fg-muted'
            )}
            title={event.name}
          >
            {event.name}
          </h3>

          <div className="mt-1.5 flex min-w-0 items-center gap-2 text-[0.8125rem] text-fg-muted">
            <EventTypeBadge type={event.eventType} isFlagship={event.isFlagship} isOnDemand={event.isOnDemand} />
            {/* Society is the row's trust signal — the strongest element on this
                line, leading even specialty (see SocietyChip's doc comment). */}
            {event.society && <SocietyChip name={event.society} count={societyCount} />}
            {event.specialty && (
              <>
                {event.society && <Dot />}
                <span className="min-w-0 truncate">{event.specialty}</span>
              </>
            )}
            <span className="flex min-w-0 items-center gap-2">
              {event.format && (
                <>
                  <Dot />
                  <FormatBadge format={event.format} />
                </>
              )}
              {place && (
                <>
                  <Dot />
                  <span className="min-w-0 truncate">{place}</span>
                </>
              )}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 sm:gap-4">
          <CpdLabel accredited={event.cpdAccredited} points={event.cpdPoints} className="hidden xl:inline-flex" />
          <EventStatus event={event} className="hidden md:inline-flex" />
          <PriceLabel min={event.priceMin} max={event.priceMax} currency={event.currency} href={event.organiserUrl} className="w-20 shrink-0 text-right" />
          <SaveToggle saved={saved} onToggle={onToggleSave} label={event.name} />
        </div>
      </div>

      <Link href={event.href} className="absolute inset-0 rounded-md outline-none" tabIndex={0}>
        <span className="sr-only">{event.name}</span>
      </Link>
    </div>
  )
}

function Dot() {
  return (
    <span aria-hidden className="shrink-0 text-fg-subtle">
      ·
    </span>
  )
}
