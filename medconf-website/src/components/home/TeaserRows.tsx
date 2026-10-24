// src/components/home/TeaserRows.tsx
//
// Anonymous-safe event rows for the homepage. Deliberately NOT EventRow: that
// primitive carries fee, CPD and exact-deadline strings. These rows take only
// plain strings built on the server (name, society, a date line or a relative
// deadline), so nothing else can reach the anonymous HTML or RSC payload.
// Server component; the detail page they link to is a public teaser.

import Link from 'next/link'
import { ChevronRight } from 'lucide-react'

export interface TeaserRow {
  id: number
  name: string
  /** Full society name (already resolved), or null. */
  society: string | null
  /** "13–15 Nov 2026" or "closes in 5 days". Never a fee, CPD or exact deadline. */
  meta: string
}

const HOVER =
  '[@media(hover:hover)_and_(pointer:fine)]:hover:bg-surface-hover'

export function TeaserRows({ rows }: { rows: TeaserRow[] }) {
  if (!rows.length) return null
  return (
    <ul className="overflow-hidden rounded-lg border border-border bg-surface">
      {rows.map((row) => (
        <li key={row.id} className="border-b border-border-subtle last:border-b-0">
          <Link
            href={`/conferences/${row.id}`}
            className={`group flex min-h-[4rem] items-center justify-between gap-4 px-4 py-3 transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${HOVER}`}
          >
            <span className="min-w-0">
              <span className="block text-[0.9375rem] leading-snug font-medium text-fg-strong">{row.name}</span>
              <span className="mt-0.5 flex flex-wrap gap-x-2 text-[0.8125rem] text-fg-muted">
                {row.society && <span>{row.society}</span>}
                {row.society && <span aria-hidden>·</span>}
                <span className="type-numeric">{row.meta}</span>
              </span>
            </span>
            <ChevronRight className="size-4 shrink-0 text-fg-subtle" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  )
}
