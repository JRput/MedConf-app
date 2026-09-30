import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { EventType } from '@/lib/types'

const LABEL: Record<EventType, string> = {
  conference: 'Conference',
  course: 'Course',
  workshop: 'Workshop',
}

const VARIANT = {
  conference: 'conference',
  course: 'course',
  workshop: 'workshop',
} as const

/**
 * The single type tag a directory row is allowed. The audit's rule (one type
 * tag, never four simultaneous badges) is enforced here: flagship and on-demand
 * are rendered as *modifiers of the same tag*, not extra badges.
 */
export function EventTypeBadge({
  type,
  isFlagship = false,
  isOnDemand = false,
  className,
}: {
  type: EventType
  isFlagship?: boolean
  isOnDemand?: boolean
  className?: string
}) {
  const label = isOnDemand
    ? 'On-demand'
    : isFlagship && type === 'conference'
      ? 'Major conference'
      : LABEL[type]

  return (
    <Badge variant={isOnDemand ? 'neutral' : VARIANT[type]} className={cn('uppercase tracking-[0.04em]', className)}>
      {label}
    </Badge>
  )
}
