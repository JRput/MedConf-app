import { Badge } from '@/components/ui/badge'
import { DeadlineBadge } from './DeadlineBadge'
import { daysUntil } from '@/lib/format'
import type { DirectoryEvent } from '@/lib/directory'

/**
 * Exactly ONE status badge per row.
 *
 * The audit's finding was that up to four badges fired at once and the row
 * stopped communicating anything. Priority, highest first:
 *   1. Sold out            — changes whether you can act at all
 *   2. Abstract deadline   — time-critical, and only inside 14 days
 *   3. On-demand expiry    — same urgency logic, different verb
 *   4. Abstracts open      — useful, not urgent
 *   5. nothing
 */
export function EventStatus({ event, className }: { event: DirectoryEvent; className?: string }) {
  if (event.isSoldOut) {
    return (
      <Badge variant="danger" className={className}>
        Sold out
      </Badge>
    )
  }

  const deadlineDays = daysUntil(event.abstractDeadline)
  if (event.abstractOpen && deadlineDays !== null && deadlineDays >= 0 && deadlineDays <= 14) {
    return <DeadlineBadge deadline={event.abstractDeadline} className={className} />
  }

  if (event.isOnDemand) {
    const days = daysUntil(event.startDate) // for on-demand rows start_date is the access deadline
    if (days !== null && days >= 0 && days <= 30) {
      return (
        <Badge variant={days <= 7 ? 'warning' : 'neutral'} className={className}>
          {days === 0 ? 'Access ends today' : `Access ends in ${days} days`}
        </Badge>
      )
    }
    return null
  }

  if (event.abstractOpen) {
    return <DeadlineBadge deadline={event.abstractDeadline} note={event.abstractDeadlineNote} className={className} />
  }

  return null
}
