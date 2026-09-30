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
 *   unknown  no pricing scraped yet → "Price TBC", never a blank cell
 */
export function PriceLabel({
  min,
  max,
  currency = 'GBP',
  size = 'sm',
  className,
}: {
  min: number | null | undefined
  max?: number | null
  currency?: string | null
  size?: 'sm' | 'md'
  className?: string
}) {
  const text = size === 'md' ? 'text-[0.9375rem]' : 'text-[0.8125rem]'

  if (min === null || min === undefined) {
    return <span className={cn('text-fg-subtle', text, className)}>Price TBC</span>
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
