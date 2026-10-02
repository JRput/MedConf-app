import { EventCardCompact } from '@/components/domain/EventCardCompact'
import type { DirectoryEvent } from '@/lib/directory'

/** Up to 4 nearby events in the same canonical specialty — presentational
 *  only; the save-state wiring that the directory gives EventCardCompact
 *  isn't available here (no client state on this server-rendered section),
 *  so save just isn't offered on these cards. */
export function RelatedEvents({ events }: { events: DirectoryEvent[] }) {
  if (events.length === 0) return null

  return (
    <section className="space-y-3">
      <h2 className="type-h3 text-fg-strong">Related events</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {events.map((e) => (
          <EventCardCompact key={e.id} event={e} />
        ))}
      </div>
    </section>
  )
}
