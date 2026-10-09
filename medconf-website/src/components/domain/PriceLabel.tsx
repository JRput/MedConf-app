import { ArrowUpRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatMoney } from '@/lib/format'

/**
 * Price is one of the top three decision factors, so it gets the mono face and
 * tabular figures — a column of prices should scan vertically.
 *
 * Four states, all real in the data:
 *   free     min === 0 and no paid tier
 *   exact    one tier, or min === max
 *   from     several tiers → "from £185" (the cheapest is what a registrar cares
 *            about; the full band lives on the detail page)
 *   unknown  no pricing scraped yet → "See organiser site", never a blank cell.
 *            With `href` it is a small external link to the organiser (it stops
 *            click propagation and sits above a row's stretched link, so the
 *            row still opens the event when anything else is clicked).
 */
export function PriceLabel({
  min,
  max,
  currency = 'GBP',
  size = 'sm',
  href,
  className,
}: {
  min: number | null | undefined
  max?: number | null
  currency?: string | null
  size?: 'sm' | 'md'
  /** Organiser URL; only used in the unknown state. */
  href?: string | null
  className?: string
}) {
  const text = size === 'md' ? 'text-[0.9375rem]' : 'text-[0.8125rem]'

  if (min === null || min === undefined) {
    if (href) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className={cn(
            'relative z-10 inline-flex items-center gap-0.5 whitespace-nowrap text-fg-subtle hover:text-brand-text hover:underline',
            text,
            className
          )}
        >
          See organiser site
          <ArrowUpRight className="size-3 shrink-0" strokeWidth={1.75} aria-hidden />
        </a>
      )
    }
    return <span className={cn('text-fg-subtle', text, className)}>See organiser site</span>
  }

  if (min === 0 && (max === 0 || max === null || max === undefined)) {
    return (
      <span className={cn('font-medium text-ok-text', text, className)}>Free</span>
    )
  }

  const hasRange = typeof max === 'number' && max > min

  return (
    <span className={cn('type-numeric font-medium text-fg', text, className)}>
      {hasRange && <span className="mr-1 font-sans text-[0.6875rem] font-normal text-fg-subtle">from</span>}
      {formatMoney(min, currency)}
    </span>
  )
}
