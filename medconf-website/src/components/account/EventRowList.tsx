'use client'

import type { ReactNode } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { EventRow } from '@/components/domain/EventRow'
import { EventCardCompact } from '@/components/domain/EventCardCompact'
import type { DirectoryEvent } from '@/lib/directory'

/**
 * The dense-row / compact-card responsive switch from the directory's
 * ResultsList, lifted out so the dashboard's three lists and /saved can all
 * render a plain array of DirectoryEvent the same way, without the
 * directory's own error/empty/broaden-dates affordances baked in — each
 * caller supplies its own `emptyState`.
 */
export function EventRowList({
  events,
  savedIds,
  onToggleSave,
  loading = false,
  skeletonCount = 3,
  emptyState,
}: {
  events: DirectoryEvent[]
  savedIds: Set<number>
  onToggleSave?: (id: number, next: boolean) => void
  loading?: boolean
  skeletonCount?: number
  emptyState?: ReactNode
}) {
  if (loading) return <SkeletonRows count={skeletonCount} />
  if (events.length === 0) return <>{emptyState ?? null}</>

  return (
    <div>
      <div className="hidden overflow-hidden rounded-lg border border-border bg-surface sm:block">
        {events.map((event) => (
          <EventRow
            key={event.id}
            event={event}
            saved={savedIds.has(event.id)}
            onToggleSave={onToggleSave ? (next) => onToggleSave(event.id, next) : undefined}
          />
        ))}
      </div>
      <div className="space-y-2.5 sm:hidden">
        {events.map((event) => (
          <EventCardCompact
            key={event.id}
            event={event}
            saved={savedIds.has(event.id)}
            onToggleSave={onToggleSave ? (next) => onToggleSave(event.id, next) : undefined}
          />
        ))}
      </div>
    </div>
  )
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: count }).map((_, i) => (
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
