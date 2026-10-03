'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { societyInfo, type SocietyKind } from '@/lib/taxonomy/societies'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

const KIND_LABEL: Record<SocietyKind, string> = {
  'royal-college': 'Royal College',
  faculty: 'Faculty',
  specialist: 'Specialist society',
  international: 'International society',
  defence: 'Medical defence organisation',
  other: 'Society',
}

/**
 * The society is the row's trust signal — "this came from the RCP" — so it is
 * the strongest element on the row's second line, not a quiet attribution
 * afterthought (see ../../../../reports/website-audit/ux.md #2/#5 and the W2
 * owner decision to drop the 44-pill source wall). Renders the FULL society
 * name (never the short code) and opens a small popover on hover/focus with
 * the society's kind, country, optional live count, and a link that filters
 * the directory to just that society.
 */
export function SocietyChip({
  name,
  count,
  className,
}: {
  /** `scraper_sources.society` short code (see taxonomy/societies.ts), not source_id. */
  name: string | null | undefined
  /** Upcoming-event count for this society, when the caller has it (e.g. from directory_facets). */
  count?: number
  className?: string
}) {
  if (!name) return null
  const info = societyInfo(name)
  const label = info?.name ?? name

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
          }}
          className={cn(
            // Never truncated — the owner's explicit call (see this file's
            // doc comment). `shrink-0` stops a flex ancestor from squeezing
            // it before anything else; truncate specialty/location instead.
            'relative z-10 shrink-0 rounded-xs text-[0.8125rem] font-medium whitespace-nowrap text-fg',
            'underline-offset-2 hover:text-brand-text hover:underline',
            'focus-visible:text-brand-text focus-visible:underline focus-visible:outline-none',
            className
          )}
          title={label}
        >
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-64"
        onClick={(e) => e.stopPropagation()}
        onPointerDownOutside={(e) => e.stopPropagation()}
      >
        <div className="space-y-2">
          <p className="text-[0.875rem] font-semibold text-fg-strong">{label}</p>
          <p className="type-mono-label text-fg-subtle">
            {info ? KIND_LABEL[info.kind] : 'Society'}
            {info?.country ? ` · ${info.country}` : ''}
          </p>
          {typeof count === 'number' && (
            <p className="text-[0.8125rem] text-fg-muted">
              {count} upcoming event{count === 1 ? '' : 's'}
            </p>
          )}
          <Link
            href={`/conferences?society=${encodeURIComponent(name)}`}
            className="inline-block text-[0.8125rem] font-medium text-brand-text hover:underline"
          >
            See all events →
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}
