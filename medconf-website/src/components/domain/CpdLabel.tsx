import { BadgeCheck } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Two genuinely different facts, so two renderings:
 *   points known  → "6 CPD" (the number is the whole value — mono, tabular)
 *   accredited only → a tick + "CPD" (we know it counts, we don't know for how much)
 *   neither        → nothing at all; "not accredited" is not a claim we can make
 *                    from the scrape, so we must not imply it.
 */
export function CpdLabel({
  accredited,
  points,
  size = 'sm',
  className,
}: {
  accredited: boolean
  points?: number | null
  size?: 'sm' | 'md'
  className?: string
}) {
  if (!accredited) return null

  const text = size === 'md' ? 'text-[0.8125rem]' : 'text-[0.75rem]'

  return (
    <span
      className={cn('inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-ok-text', text, className)}
      title={points ? `${points} CPD points` : 'CPD accredited'}
    >
      <BadgeCheck className={size === 'md' ? 'size-4' : 'size-3.5'} strokeWidth={1.75} aria-hidden />
      {points ? (
        <>
          <span className="type-numeric font-medium">{points}</span>
          <span className="font-medium">CPD</span>
        </>
      ) : (
        <span className="font-medium">CPD</span>
      )}
    </span>
  )
}
