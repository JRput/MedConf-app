'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { locationLine, type DirectoryEvent } from '@/lib/directory'
import { DateBlock } from './DateBlock'
import { EventTypeBadge } from './EventTypeBadge'
import { FormatBadge } from './FormatBadge'
import { PriceLabel } from './PriceLabel'
import { CpdLabel } from './CpdLabel'
import { SocietyChip } from './SocietyChip'
import { EventStatus } from './EventStatus'
import { SaveToggle } from './SaveToggle'

/**
 * The dense desktop row — the directory's default unit from W2 onwards.
 *
 * Five facts, left to right: when · what · where/how · how much · one status.
 * Everything else (abstract detail, source URL, full pricing band, CPD
 * breakdown) belongs to the detail page.
 *
 * The whole row is one link via a stretched overlay, so the click target is the
 * full width; the save control opts out with its own stacking context. Keyboard
 * users get a single tab stop for the row plus one for save, and the ring is
 * drawn on the row rather than on the invisible overlay.
 */
export function EventRow({
  event,
  saved = false,
  onToggleSave,
  className,
}: {
  event: DirectoryEvent
  saved?: boolean
  onToggleSave?: (next: boolean) => void
  className?: string
}) {
  const place = locationLine(event)

  return (
    <div
      className={cn(
        'group relative grid grid-cols-[3.5rem_minmax(0,1fr)_auto] items-center gap-x-4',
        'border-b border-border-subtle px-3 py-3 last:border-b-0',
        'transition-colors duration-150',
        'hover:bg-surface-hover',
        'has-[a:focus-visible]:bg-surface-hover has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring has-[a:focus-visible]:ring-inset',
        className
      )}
    >
      <DateBlock startDate={event.startDate} endDate={event.endDate} />

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
          {event.specialty && (
            <>
              <span className="truncate">{event.specialty}</span>
            </>
          )}
          <span className="hidden items-center gap-2 lg:flex">
            {event.format && (
              <>
                <Dot />
                <FormatBadge format={event.format} />
              </>
            )}
            {place && (
              <>
                <Dot />
                <span className="truncate">{place}</span>
              </>
            )}
            {event.society && (
              <>
                <Dot />
                <SocietyChip name={event.society} />
              </>
            )}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 sm:gap-4">
        <CpdLabel accredited={event.cpdAccredited} points={event.cpdPoints} className="hidden xl:inline-flex" />
        <EventStatus event={event} className="hidden md:inline-flex" />
        <PriceLabel min={event.priceMin} max={event.priceMax} currency={event.currency} className="w-20 shrink-0 text-right" />
        <SaveToggle saved={saved} onToggle={onToggleSave} label={event.name} />
      </div>

      <Link href={event.href} className="absolute inset-0 rounded-md outline-none" tabIndex={0}>
        <span className="sr-only">{event.name}</span>
      </Link>
    </div>
  )
}

function Dot() {
  return (
    <span aria-hidden className="text-fg-subtle">
      ·
    </span>
  )
}
