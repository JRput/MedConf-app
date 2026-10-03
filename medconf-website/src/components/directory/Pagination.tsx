'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

/** Numbered pagination, not infinite scroll — the audit's #1 finding was an
 * unpaginated 1,194-row page; this keeps every page a bounded, fast render. */
export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (pageCount <= 1) return null

  const pages = pageNumbers(page, pageCount)

  return (
    <nav className="flex items-center justify-center gap-1" aria-label="Pagination">
      <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <ChevronLeft />
      </Button>
      {pages.map((p, i) =>
        p === '…' ? (
          <span key={`ellipsis-${i}`} className="px-1.5 text-fg-subtle">
            …
          </span>
        ) : (
          <Button
            key={p}
            variant={p === page ? 'default' : 'outline'}
            size="icon-sm"
            aria-current={p === page ? 'page' : undefined}
            onClick={() => onChange(p)}
            className={cn('type-numeric')}
          >
            {p}
          </Button>
        )
      )}
      <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={page >= pageCount} onClick={() => onChange(page + 1)}>
        <ChevronRight />
      </Button>
    </nav>
  )
}

function pageNumbers(current: number, count: number): (number | '…')[] {
  const out: (number | '…')[] = []
  const add = (n: number) => out.push(n)
  const windowStart = Math.max(2, current - 1)
  const windowEnd = Math.min(count - 1, current + 1)

  add(1)
  if (windowStart > 2) out.push('…')
  for (let p = windowStart; p <= windowEnd; p++) add(p)
  if (windowEnd < count - 1) out.push('…')
  if (count > 1) add(count)
  return out
}
