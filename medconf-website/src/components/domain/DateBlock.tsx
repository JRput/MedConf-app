import { cn } from '@/lib/utils'
import { dateParts, formatDateRange } from '@/lib/format'

/**
 * The calendar-leaf date stack that anchors every directory row: a large day
 * numeral over a mono month label. A multi-day event shows its span as
 * "13–15"; one that crosses a month shows the end month underneath.
 *
 * The year is only printed when the event is not in the current year — most
 * rows are this year and the repetition is noise.
 */
export function DateBlock({
  startDate,
  endDate,
  /** The event has already started but hasn't finished — see lib/format.ts `isOngoing`.
   *  Shows "Until <end date>" instead of the now-stale start date. */
  ongoing = false,
  size = 'md',
  className,
}: {
  startDate: string | null
  endDate?: string | null
  ongoing?: boolean
  size?: 'sm' | 'md'
  className?: string
}) {
  const start = dateParts(startDate)
  const end = dateParts(endDate)
  const thisYear = new Date().getFullYear()

  if (!start) {
    return (
      <div
        className={cn(
          'flex shrink-0 flex-col items-center justify-center rounded-md border border-dashed border-border bg-surface-muted text-fg-subtle',
          size === 'md' ? 'h-14 w-14' : 'h-11 w-11',
          className
        )}
        aria-label="Date to be confirmed"
      >
        <span className="type-mono-label">TBC</span>
      </div>
    )
  }

  if (ongoing && end) {
    return (
      <div
        className={cn(
          'flex shrink-0 flex-col items-center justify-center rounded-md border border-warn-border bg-warn-subtle',
          size === 'md' ? 'h-14 w-14 gap-0.5' : 'h-11 w-11',
          className
        )}
        aria-label={`Ongoing — until ${formatDateRange(startDate, endDate ?? null)}`}
      >
        <span className={cn('type-numeric font-semibold leading-none text-fg-strong', size === 'md' ? 'text-lg' : 'text-sm')}>{end.day}</span>
        <span className="type-mono-label text-fg-muted">{end.month}</span>
        {size === 'md' && <span className="type-mono-label text-[0.5625rem] leading-none text-warn-text">UNTIL</span>}
      </div>
    )
  }

  const sameMonth = !end || (end.month === start.month && end.year === start.year)
  const dayText = end && end.day !== start.day && sameMonth ? `${start.day}–${end.day}` : start.day
  // A cross-month range would squeeze "APR–MAY" into an 11px label; the full
  // span is already on the meta line and in this block's aria-label.
  const monthText = start.month
  const showYear = start.year !== thisYear

  return (
    <div
      className={cn(
        'flex shrink-0 flex-col items-center justify-center rounded-md border border-border bg-surface-muted',
        size === 'md' ? 'h-14 w-14 gap-0.5' : 'h-11 w-11',
        className
      )}
      aria-label={formatDateRange(startDate, endDate ?? null)}
    >
      <span
        className={cn(
          'type-numeric font-semibold leading-none text-fg-strong',
          dayText.length > 2 ? (size === 'md' ? 'text-[0.9375rem]' : 'text-xs') : size === 'md' ? 'text-lg' : 'text-sm'
        )}
      >
        {dayText}
      </span>
      <span className="type-mono-label text-fg-muted">{monthText}</span>
      {showYear && size === 'md' && (
        <span className="type-mono-label text-[0.5625rem] leading-none text-fg-subtle">{start.year}</span>
      )}
    </div>
  )
}
