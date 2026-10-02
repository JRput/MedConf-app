'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { formatDateRange } from '@/lib/format'
import { locationLine, type DirectoryEvent } from '@/lib/directory'
import { EventTypeBadge } from './EventTypeBadge'
import { FormatBadge } from './FormatBadge'
import { PriceLabel } from './PriceLabel'
import { CpdLabel } from './CpdLabel'
import { SocietyChip } from './SocietyChip'
import { EventStatus } from './EventStatus'
import { SaveToggle } from './SaveToggle'

/**
 * The mobile unit. Same five facts as EventRow, restacked for a 390px viewport:
 * the date becomes a mono line rather than a leaf block (a 56px square next to
 * a two-line title wastes a third of the width), and the title is allowed two
 * lines because truncating to one at this width loses the specialty cue that
 * usually sits at the end of a long conference name.
 */
export function EventCardCompact({
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

  return (
    <article
      className={cn(
        'group relative rounded-lg border border-border bg-surface p-3',
        'transition-colors duration-150',
        'active:bg-surface-hover',
        'has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring has-[a:focus-visible]:ring-offset-2 has-[a:focus-visible]:ring-offset-bg',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="type-mono-label text-fg-muted">{formatDateRange(event.startDate, event.endDate)}</span>
        <SaveToggle saved={saved} onToggle={onToggleSave} label={event.name} className="-mt-1.5 -mr-1.5" />
      </div>

      <h3
        className={cn(
          'mt-1.5 line-clamp-2 text-[0.9375rem] font-medium leading-snug text-fg-strong',
          event.isSoldOut && 'text-fg-muted'
        )}
      >
        {event.name}
      </h3>

      {/* Society leads this line — the row's trust signal, strongest element
          here — before specialty (see SocietyChip's doc comment). */}
      {(event.society || event.specialty) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-fg-muted">
          {event.society && <SocietyChip name={event.society} count={societyCount} />}
          {event.specialty && (
            <>
              {event.society && <span aria-hidden className="text-fg-subtle">·</span>}
              <span className="truncate">{event.specialty}</span>
            </>
          )}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[0.8125rem] text-fg-muted">
        <EventTypeBadge type={event.eventType} isFlagship={event.isFlagship} isOnDemand={event.isOnDemand} />
        {event.format && <FormatBadge format={event.format} />}
        {place && <span className="truncate">{place}</span>}
        <CpdLabel accredited={event.cpdAccredited} points={event.cpdPoints} />
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border-subtle pt-2.5">
        <PriceLabel min={event.priceMin} max={event.priceMax} currency={event.currency} size="md" />
        <EventStatus event={event} />
      </div>

      <Link href={event.href} className="absolute inset-0 rounded-lg outline-none">
        <span className="sr-only">{event.name}</span>
      </Link>
    </article>
  )
}
