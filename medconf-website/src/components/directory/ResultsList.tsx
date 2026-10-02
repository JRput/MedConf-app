'use client'

import { AlertTriangle, SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EventRow } from '@/components/domain/EventRow'
import { EventCardCompact } from '@/components/domain/EventCardCompact'
import type { DirectoryEvent } from '@/lib/directory'
import type { DirectoryFacets } from '@/lib/directory-query'

export function ResultsList({
  rows,
  loading,
  error,
  facets,
  savedIds,
  onToggleSave,
  onClearAll,
  onBroadenDate,
  hasDateFilter,
  onRetry,
}: {
  rows: DirectoryEvent[]
  loading: boolean
  error: string | null
  facets: DirectoryFacets | null
  savedIds: Set<number>
  onToggleSave?: (id: number, next: boolean) => void
  onClearAll: () => void
  onBroadenDate: () => void
  hasDateFilter: boolean
  onRetry: () => void
}) {
  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-danger-border bg-danger-subtle px-6 py-16 text-center">
        <AlertTriangle className="size-8 text-danger-text" aria-hidden />
        <p className="text-[0.9375rem] font-medium text-fg-strong">Couldn&apos;t load the directory</p>
        <p className="max-w-sm text-[0.8125rem] text-fg-muted">{error}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    )
  }

  if (loading && rows.length === 0) {
    return <SkeletonRows />
  }

  if (!loading && rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-border bg-surface px-6 py-16 text-center">
        <SearchX className="size-8 text-fg-subtle" aria-hidden />
        <p className="text-[0.9375rem] font-medium text-fg-strong">No events match your filters</p>
        <p className="max-w-sm text-[0.8125rem] text-fg-muted">Try clearing a filter, or widen the date range.</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onClearAll}>
            Clear all filters
          </Button>
          {hasDateFilter && (
            <Button variant="outline" size="sm" onClick={onBroadenDate}>
              Broaden dates
            </Button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className={loading ? 'opacity-60 transition-opacity duration-150' : 'transition-opacity duration-150'}>
      <div className="hidden overflow-hidden rounded-lg border border-border bg-surface sm:block">
        {rows.map((event) => (
          <EventRow
            key={event.id}
            event={event}
            saved={savedIds.has(event.id)}
            societyCount={event.society ? facets?.society[event.society] : undefined}
            onToggleSave={onToggleSave ? (next) => onToggleSave(event.id, next) : undefined}
          />
        ))}
      </div>
      <div className="space-y-2.5 sm:hidden">
        {rows.map((event) => (
          <EventCardCompact
            key={event.id}
            event={event}
            saved={savedIds.has(event.id)}
            societyCount={event.society ? facets?.society[event.society] : undefined}
            onToggleSave={onToggleSave ? (next) => onToggleSave(event.id, next) : undefined}
          />
        ))}
      </div>
    </div>
  )
}

function SkeletonRows() {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-lg border border-border bg-surface p-3">
          <Skeleton className="size-14 shrink-0 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-3/5" />
            <Skeleton className="h-3 w-2/5" />
          </div>
          <Skeleton className="h-3.5 w-14 shrink-0" />
        </div>
      ))}
    </div>
  )
}
