import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { daysUntil } from '@/lib/format'

/**
 * Abstract-submission urgency — the one status signal allowed to shout.
 *
 * Urgency bands (calendar days, not hours — the source data is day-precision):
 *   0–3   danger   "closes in 2 days"
 *   4–14  warning  "closes in 11 days"
 *   15+   neutral  "abstracts open"   (a date three months out is not urgent;
 *                                      showing it in amber trains people to
 *                                      ignore amber)
 *   past  nothing — the caller decides whether to show "closed"
 *
 * `note` covers the curator case where submissions are confirmed open but the
 * organiser has published no date.
 */
export function DeadlineBadge({
  deadline,
  note,
  label = 'Abstracts',
  showClosed = false,
  className,
}: {
  deadline: string | null
  note?: string | null
  label?: string
  showClosed?: boolean
  className?: string
}) {
  const days = daysUntil(deadline)

  if (days === null) {
    if (!note) return null
    return (
      <Badge variant="info" className={className}>
        {label} open
      </Badge>
    )
  }

  if (days < 0) {
    if (!showClosed) return null
    return (
      <Badge variant="neutral" className={cn('line-through decoration-1', className)}>
        {label} closed
      </Badge>
    )
  }

  const variant = days <= 3 ? 'danger' : days <= 14 ? 'warning' : 'info'
  const text =
    days === 0
      ? `${label} close today`
      : days === 1
        ? `${label} close tomorrow`
        : days <= 14
          ? `${label} close in ${days} days`
          : `${label} open`

  return (
    <Badge variant={variant} className={className}>
      {text}
    </Badge>
  )
}
