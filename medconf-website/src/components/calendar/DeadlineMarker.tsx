'use client'

import { FileClock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DirectoryEvent } from '@/lib/directory'
import { deadlineCountdown, longDateLabel, todayIso } from '@/lib/calendar'
import { societyInfo } from '@/lib/taxonomy/societies'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * The abstract-deadline marker on a day cell.
 *
 * It used to be a decorative icon with a `title`, which told you a deadline
 * existed but not whose — the one question a doctor actually has when they see
 * it. It is now a control: hovering names the event, clicking opens that
 * event's panel with the deadline called out, and a day carrying several
 * deadlines gets a count and a list to choose from.
 *
 * Two forms, same button:
 *   - `labelled` (wide cells) — a warn-toned chip reading "Abstracts: <title>",
 *     so a deadline scans as a dated item rather than a mystery glyph.
 *   - icon-only (narrow cells) — the glyph plus a count when there is more
 *     than one.
 *
 * HIT AREA. The visible chip is ~18px tall, which is far too small to hit.
 * The `::after` box expands it UPWARDS over the day-number row — 32px by
 * default, 44px on a coarse pointer. Upwards specifically: the event chips sit
 * below the marker, and an expanded hit area growing downwards would eat their
 * clicks on exactly the days that are busiest.
 */
const HIT_AREA = [
  'after:absolute after:inset-x-0 after:bottom-0 after:h-8 after:content-[""]',
  '[@media(pointer:coarse)]:after:h-11',
].join(' ')

/**
 * The inline label is deliberately NOT `type-mono-label`: that utility
 * uppercases, and an all-caps conference title in a ~120px cell is both harder
 * to read and roughly half as many characters before it truncates
 * ("ABSTRACTS: EM EDU…" against "Abstracts: EM Educators…").
 */
const LABEL = 'hidden min-w-0 flex-1 truncate text-[0.625rem] leading-none font-medium @row-md:inline'

const CHIP = [
  'relative flex w-full items-center gap-1 overflow-hidden rounded-xs border px-1 py-px text-left',
  'border-warn-border bg-warn-subtle text-warn-text',
  'transition-colors duration-150 hover:bg-warn-subtle hover:brightness-[0.97] dark:hover:brightness-[1.12]',
  'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-bg focus-visible:outline-none',
].join(' ')

export function DeadlineMarker({
  iso,
  events,
  locale,
  onSelect,
  className,
}: {
  iso: string
  /** Saved events whose abstract deadline is this day. Never empty. */
  events: DirectoryEvent[]
  locale: string
  /** Opens the event's side panel with the deadline highlighted. */
  onSelect?: (event: DirectoryEvent) => void
  className?: string
}) {
  if (events.length === 0) return null
  const today = todayIso()
  const dayLabel = longDateLabel(iso, locale)

  // ---- one deadline: a tooltip naming it, click straight through to the panel
  if (events.length === 1) {
    const event = events[0]
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => onSelect?.(event)}
            aria-label={`Abstracts close ${dayLabel} — ${event.name}. Open event details.`}
            className={cn(CHIP, HIT_AREA, className)}
          >
            <FileClock className="size-3 shrink-0" strokeWidth={2} aria-hidden />
            {/* The label only appears where a cell is wide enough to hold a
                readable fragment of a title; below that the glyph carries it. */}
            <span className={LABEL}>Abstracts: {event.name}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="font-medium">Abstracts close · {event.name}</p>
          <p className="opacity-80">
            {dayLabel} — {deadlineCountdown(iso, today)}
          </p>
        </TooltipContent>
      </Tooltip>
    )
  }

  // ---- several: a count, and a list to pick from
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${events.length} abstract deadlines on ${dayLabel}`}
          className={cn(CHIP, HIT_AREA, className)}
        >
          <FileClock className="size-3 shrink-0" strokeWidth={2} aria-hidden />
          {/* The count badge is the icon-only form's only way to say "more
              than one"; once the label spells that out, repeating it as a
              badge just reads as "2 Abstracts: 2 deadlines". */}
          <span className="type-mono-label text-[0.5625rem] leading-none @row-md:hidden">{events.length}</span>
          <span className={LABEL}>Abstracts: {events.length} deadlines</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-2">
        <p className="px-1 pb-1.5 type-mono-label text-fg-subtle">
          {events.length} abstract deadlines · {deadlineCountdown(iso, today)}
        </p>
        <div className="space-y-1">
          {events.map((event) => (
            <button
              key={event.id}
              type="button"
              onClick={() => onSelect?.(event)}
              className={cn(
                'flex w-full items-start gap-2 rounded-sm border border-warn-border bg-warn-subtle px-2 py-1.5 text-left',
                'transition-colors duration-150 hover:brightness-[0.97] dark:hover:brightness-[1.12]',
                'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
              )}
            >
              <FileClock className="mt-0.5 size-3 shrink-0 text-warn-text" strokeWidth={2} aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-[0.8125rem] leading-snug font-medium text-fg-strong">{event.name}</span>
                {event.society && (
                  <span className="mt-0.5 block type-mono-label text-fg-subtle">
                    {societyInfo(event.society)?.name ?? event.society}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
