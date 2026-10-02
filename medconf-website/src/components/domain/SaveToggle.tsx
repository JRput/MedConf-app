'use client'

import { Bookmark } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Presentational save control — no data access, so it works identically in the
 * directory, the detail page and the /design tile. W2 wires it to `useSaved`.
 *
 * It sits inside a row whose whole surface is a link, so it needs its own
 * stacking context (`relative z-10`) to stay clickable, and a ::after box that
 * expands the hit area to 44px on touch without changing the visual size.
 */
export function SaveToggle({
  saved,
  onToggle,
  label,
  className,
}: {
  saved: boolean
  onToggle?: (next: boolean) => void
  /** Event name, so screen readers hear which row is being saved. */
  label?: string
  className?: string
}) {
  return (
    <button
      type="button"
      aria-pressed={saved}
      aria-label={`${saved ? 'Remove' : 'Save'}${label ? ` ${label}` : ''}`}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onToggle?.(!saved)
      }}
      className={cn(
        'relative z-10 inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md',
        'text-fg-subtle transition-colors duration-150',
        'hover:bg-surface-active hover:text-fg',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg focus-visible:outline-none',
        // 44x44 touch target without a 44px visual footprint
        'after:absolute after:top-1/2 after:left-1/2 after:size-11 after:-translate-x-1/2 after:-translate-y-1/2 after:content-[""]',
        saved && 'text-brand-text hover:text-brand-text',
        className
      )}
    >
      <Bookmark className="size-[18px]" strokeWidth={1.75} fill={saved ? 'currentColor' : 'none'} aria-hidden />
    </button>
  )
}
