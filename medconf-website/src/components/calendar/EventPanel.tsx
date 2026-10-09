'use client'

import Link from 'next/link'
import { ArrowUpRight, BookmarkX, Download, FileClock, MapPin, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { locationLine, type DirectoryEvent } from '@/lib/directory'
import { formatDateRange, isOngoing } from '@/lib/format'
import { deadlineCountdown, shortDateLabel, todayIso } from '@/lib/calendar'
import { downloadIcsFeed } from '@/lib/ics'
import { societyInfo } from '@/lib/taxonomy/societies'
import { DateBlock } from '@/components/domain/DateBlock'
import { EventTypeBadge } from '@/components/domain/EventTypeBadge'
import { FormatBadge } from '@/components/domain/FormatBadge'
import { PriceLabel } from '@/components/domain/PriceLabel'
import { CpdLabel } from '@/components/domain/CpdLabel'
import { DeadlineBadge } from '@/components/domain/DeadlineBadge'
import { EventStatus } from '@/components/domain/EventStatus'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { LG_QUERY, useMediaQuery } from './useMediaQuery'
import { useLocale } from './useLocale'

/**
 * What a chip opens: the event's summary, close enough to the detail page to
 * answer "is this the one I meant?" without the round trip, and three actions
 * — open it, export it, drop it.
 *
 * Rendered two ways by `EventPanelHost` below: an inline right-hand column on
 * large screens, a Sheet below that. The inline version is deliberate — a
 * calendar is a comparison surface, and an overlay that dims the grid hides
 * the thing you are comparing against.
 */
export function EventPanelBody({
  event,
  onClose,
  onUnsave,
  highlightDeadline = false,
  className,
}: {
  event: DirectoryEvent
  onClose?: () => void
  onUnsave?: (event: DirectoryEvent) => void
  /** Opened from a deadline marker — lead with the deadline, not the event. */
  highlightDeadline?: boolean
  className?: string
}) {
  const locale = useLocale()
  const place = locationLine(event)
  const ongoing = !event.isOnDemand && isOngoing(event.startDate, event.endDate)
  const society = event.society ? (societyInfo(event.society)?.name ?? event.society) : null

  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div className="flex items-start gap-3 border-b border-border px-4 py-4">
        <DateBlock startDate={event.startDate} endDate={event.endDate} ongoing={ongoing} />
        <div className="min-w-0 flex-1">
          <p className="type-mono-label text-fg-subtle">
            {event.startDate ? formatDateRange(event.startDate, event.endDate) : 'Date to be confirmed'}
          </p>
          <h2 className="mt-1 text-[0.9375rem] leading-snug font-semibold text-fg-strong">{event.name}</h2>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className={cn(
              'relative -mt-1 -mr-1 inline-flex size-8 shrink-0 items-center justify-center rounded-md',
              'text-fg-subtle transition-colors duration-150 hover:bg-surface-active hover:text-fg',
              'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              'after:absolute after:top-1/2 after:left-1/2 after:size-11 after:-translate-x-1/2 after:-translate-y-1/2 after:content-[""]'
            )}
          >
            <X className="size-4" strokeWidth={2} aria-hidden />
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* When the panel was opened FROM a deadline marker, the deadline is
            the thing being asked about — so it leads, with the countdown spelt
            out, rather than sitting four fields down as a bare date. */}
        {highlightDeadline && event.abstractDeadline && (
          <div className="flex items-start gap-2 rounded-md border border-warn-border bg-warn-subtle px-3 py-2">
            <FileClock className="mt-0.5 size-4 shrink-0 text-warn-text" strokeWidth={2} aria-hidden />
            <p className="type-small font-medium text-warn-text">
              Abstract deadline: {shortDateLabel(event.abstractDeadline, locale)} —{' '}
              {deadlineCountdown(event.abstractDeadline, todayIso())}
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <EventTypeBadge type={event.eventType} isFlagship={event.isFlagship} isOnDemand={event.isOnDemand} />
          <EventStatus event={event} />
          <DeadlineBadge deadline={event.abstractDeadline} note={event.abstractDeadlineNote} showClosed />
        </div>

        {society && (
          <Field label="Organiser">
            <p className="text-[0.875rem] font-medium text-fg">{society}</p>
          </Field>
        )}

        {event.specialty && (
          <Field label="Specialty">
            <p className="text-[0.875rem] text-fg">{event.specialty}</p>
          </Field>
        )}

        <Field label="Format">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {event.format && <FormatBadge format={event.format} size="md" />}
            {place && (
              <span className="inline-flex items-center gap-1.5 text-[0.875rem] text-fg-muted">
                <MapPin className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
                {place}
              </span>
            )}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="From">
            <PriceLabel min={event.priceMin} max={event.priceMax} currency={event.currency} href={event.organiserUrl} size="md" />
          </Field>
          {/* CpdLabel renders nothing when the event is not accredited, so the
              Field has to be conditional too — otherwise the panel shows a
              "CPD" heading with a blank underneath it. */}
          {event.cpdAccredited && (
            <Field label="CPD">
              <CpdLabel accredited={event.cpdAccredited} points={event.cpdPoints} />
            </Field>
          )}
        </div>

        {/* Skipped when the highlighted row above already states it — the same
            date twice in one short panel reads as a mistake. */}
        {event.abstractDeadline && !highlightDeadline && (
          <Field label="Abstract deadline">
            <p className="type-numeric text-[0.875rem] text-fg">{formatDateRange(event.abstractDeadline, null)}</p>
          </Field>
        )}
      </div>

      <div className="space-y-2 border-t border-border px-4 py-4">
        <Button asChild className="w-full">
          <Link href={event.href}>
            Open event
            <ArrowUpRight className="size-4" aria-hidden />
          </Link>
        </Button>
        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => downloadIcsFeed([event], icsName(event))}>
            <Download className="size-4" aria-hidden />
            Export .ics
          </Button>
          {onUnsave && (
            <Button variant="outline" className="flex-1" onClick={() => onUnsave(event)}>
              <BookmarkX className="size-4" aria-hidden />
              Unsave
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function icsName(event: DirectoryEvent): string {
  const slug = event.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)
  return `${slug || 'event'}.ics`
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="type-mono-label text-fg-subtle">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  )
}

/**
 * Picks the presentation. `lg` is the breakpoint where the grid can afford to
 * give up ~340px and still show a week comfortably.
 *
 * The choice is made in JS rather than with `lg:hidden` because a Sheet
 * portals its backdrop to the body: a CSS-hidden Sheet would still dim the
 * grid behind an inline panel on desktop.
 */
export function EventPanelHost({
  event,
  onClose,
  onUnsave,
  highlightDeadline = false,
}: {
  event: DirectoryEvent | null
  onClose: () => void
  onUnsave?: (event: DirectoryEvent) => void
  highlightDeadline?: boolean
}) {
  const isWide = useMediaQuery(LG_QUERY)

  if (isWide) {
    return (
      <aside
        className={cn('hidden lg:block', event ? 'lg:w-[340px] lg:shrink-0' : 'lg:w-0 lg:overflow-hidden')}
        aria-label="Event details"
      >
        {event && (
          // Sticky so the panel stays with you as the grid scrolls, and
          // scroll-capped so a long summary never pushes the page.
          <div className="sticky top-20 flex max-h-[calc(100vh-6rem)] overflow-hidden rounded-lg border border-border bg-surface shadow-sm">
            <EventPanelBody event={event} onClose={onClose} onUnsave={onUnsave} highlightDeadline={highlightDeadline} />
          </div>
        )}
      </aside>
    )
  }

  return (
    <Sheet open={Boolean(event)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" showCloseButton={false} className="w-full gap-0 p-0 sm:max-w-sm">
        {event && (
          <>
            <SheetTitle className="sr-only">{event.name}</SheetTitle>
            <EventPanelBody event={event} onClose={onClose} onUnsave={onUnsave} highlightDeadline={highlightDeadline} />
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
