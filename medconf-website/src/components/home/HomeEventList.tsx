// src/components/home/HomeEventList.tsx
//
// Renders real directory rows on the homepage using the SAME primitives the
// directory uses — EventRow on desktop, EventCardCompact on mobile (W2's
// decision, see components/directory/ResultsList.tsx). The homepage therefore
// cannot drift from /conferences visually: fix a row there and it fixes here.
//
// No save state is passed: the homepage is public and server-rendered, so
// SaveToggle renders its unsaved resting state and the row's own link carries
// the click. Signing in and saving happens on the directory/detail pages.

import { EventRow } from '@/components/domain/EventRow'
import { EventCardCompact } from '@/components/domain/EventCardCompact'
import type { DirectoryEvent } from '@/lib/directory'

export function HomeEventList({
  events,
  societyCounts,
}: {
  events: DirectoryEvent[]
  /** society short code → live event count, from queryFacets (powers SocietyChip). */
  societyCounts?: Record<string, number>
}) {
  if (!events.length) return null

  return (
    <>
      <div className="hidden overflow-hidden rounded-lg border border-border bg-surface sm:block">
        {events.map((event) => (
          <EventRow
            key={event.id}
            event={event}
            societyCount={event.society ? societyCounts?.[event.society] : undefined}
          />
        ))}
      </div>
      <div className="space-y-2.5 sm:hidden">
        {events.map((event) => (
          <EventCardCompact
            key={event.id}
            event={event}
            societyCount={event.society ? societyCounts?.[event.society] : undefined}
          />
        ))}
      </div>
    </>
  )
}
