'use client'

import { Building2, ChevronLeft, ChevronRight, Globe, MonitorSmartphone } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DirectoryEvent } from '@/lib/directory'
import type { Conference } from '@/lib/types'
import type { Segment } from '@/lib/calendar'
import { formatDateRange } from '@/lib/format'

/**
 * One event on the month grid: a chip when it covers a single day, a spanning
 * bar when it covers several.
 *
 * Both are the same component because they are the same object — a saved event
 * occupying a stretch of the user's diary. Only the width and the clipped ends
 * differ, so splitting them into two components would duplicate the colour,
 * focus and truncation rules for no gain.
 *
 * Colour comes from the event-type token triple (conference / course /
 * workshop), which is the one axis worth colour-coding here: the format is
 * carried by the glyph, and urgency by the separate deadline marker, so the
 * grid never shows two competing colour systems.
 */

const TYPE_CLASS: Record<Conference['event_type'], string> = {
  conference: 'border-type-conference-border bg-type-conference-subtle text-type-conference-text',
  course: 'border-type-course-border bg-type-course-subtle text-type-course-text',
  workshop: 'border-type-workshop-border bg-type-workshop-subtle text-type-workshop-text',
}

const FORMAT_ICON = {
  online: Globe,
  in_person: Building2,
  hybrid: MonitorSmartphone,
} as const

export function EventChip({
  segment,
  selected = false,
  onSelect,
  className,
}: {
  segment: Segment<DirectoryEvent>
  selected?: boolean
  onSelect?: (event: DirectoryEvent) => void
  className?: string
}) {
  const { event, continuesBefore, continuesAfter, length } = segment
  const Icon = event.format ? FORMAT_ICON[event.format] : null
  // Below ~3 columns there is no room for both a glyph and a readable title,
  // and the title is the thing people scan for.
  const showIcon = Boolean(Icon) && length >= 2

  return (
    <button
      type="button"
      onClick={() => onSelect?.(event)}
      aria-pressed={selected}
      title={`${event.name} — ${formatDateRange(event.startDate, event.endDate)}`}
      className={cn(
        'flex h-full w-full items-center gap-1 overflow-hidden border px-1.5 text-left',
        'text-[0.6875rem] leading-none font-medium',
        'transition-[background-color,box-shadow] duration-150',
        'hover:brightness-[0.97] dark:hover:brightness-[1.12]',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-bg focus-visible:outline-none',
        TYPE_CLASS[event.eventType],
        // A clipped end loses its radius and border so the bar reads as
        // continuing past the row edge rather than ending there.
        continuesBefore ? 'rounded-l-none border-l-0' : 'rounded-l-sm',
        continuesAfter ? 'rounded-r-none border-r-0' : 'rounded-r-sm',
        selected && 'ring-2 ring-ring ring-offset-1 ring-offset-bg',
        event.isSoldOut && 'opacity-60',
        className
      )}
    >
      {continuesBefore && <ChevronLeft className="size-2.5 shrink-0 opacity-70" strokeWidth={2.5} aria-hidden />}
      {showIcon && Icon && <Icon className="size-2.5 shrink-0 opacity-80" strokeWidth={2} aria-hidden />}
      <span className="min-w-0 flex-1 truncate">{event.name}</span>
      {continuesAfter && <ChevronRight className="size-2.5 shrink-0 opacity-70" strokeWidth={2.5} aria-hidden />}
    </button>
  )
}

/**
 * The same event as a full-width list item — used in the overflow popover, the
 * mobile day list and anywhere a chip's single line is too cramped to be fair
 * to it.
 */
export function EventChipRow({
  event,
  selected = false,
  onSelect,
  className,
}: {
  event: DirectoryEvent
  selected?: boolean
  onSelect?: (event: DirectoryEvent) => void
  className?: string
}) {
  const Icon = event.format ? FORMAT_ICON[event.format] : null

  return (
    <button
      type="button"
      onClick={() => onSelect?.(event)}
      aria-pressed={selected}
      className={cn(
        'flex w-full items-start gap-2 rounded-sm border px-2 py-1.5 text-left',
        'transition-colors duration-150',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-bg focus-visible:outline-none',
        TYPE_CLASS[event.eventType],
        selected && 'ring-2 ring-ring ring-offset-1 ring-offset-bg',
        className
      )}
    >
      {Icon && <Icon className="mt-0.5 size-3 shrink-0 opacity-80" strokeWidth={2} aria-hidden />}
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8125rem] leading-snug font-medium">{event.name}</span>
        <span className="mt-0.5 block type-mono-label opacity-80">{formatDateRange(event.startDate, event.endDate)}</span>
      </span>
    </button>
  )
}
