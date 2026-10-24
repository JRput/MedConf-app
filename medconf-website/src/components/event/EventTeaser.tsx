// src/components/event/EventTeaser.tsx
//
// The anonymous event page body. Built ONLY from PublicEventFields (see
// lib/event-public.ts): header, a short description excerpt and a LockedPanel
// naming what a free account unlocks. Server component, no hooks.

import { Calendar, MapPin, Globe, MonitorSmartphone, Building2 } from 'lucide-react'
import { EventTypeBadge } from '@/components/domain/EventTypeBadge'
import { FormatBadge } from '@/components/domain/FormatBadge'
import { LockedPanel } from '@/components/auth/LockedPanel'
import { formatDateRange } from '@/lib/format'
import { societyInfo } from '@/lib/taxonomy/societies'
import type { PublicEventFields } from '@/lib/event-public'

export const LOCKED_EVENT_ITEMS = [
  'Fees and early-bird prices',
  'CPD points',
  'Abstract deadline and submission details',
  'Venue and map',
  'Booking and organiser links',
  'Sessions and programme',
  'Save, reminders and calendar export',
]

export function EventTeaser({ event }: { event: PublicEventFields }) {
  const place =
    event.event_format === 'online' ? 'Online' : [event.city, event.region].filter(Boolean).join(', ') || 'Location TBC'
  const PlaceIcon = event.event_format === 'online' ? Globe : event.event_format === 'hybrid' ? MonitorSmartphone : event.event_format === 'in_person' ? Building2 : MapPin
  const societyName = event.society ? (societyInfo(event.society)?.name ?? event.society) : null
  const next = `/conferences/${event.id}`

  return (
    <div className="max-w-3xl space-y-8">
      <header className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <EventTypeBadge type={event.event_type} isFlagship={event.is_flagship} isOnDemand={event.is_on_demand} />
          {event.event_format && <FormatBadge format={event.event_format} />}
          {societyName && <span className="text-[0.8125rem] font-medium text-fg">{societyName}</span>}
        </div>
        <h1 className="type-h1 text-fg-strong">{event.conference_name}</h1>
        <ul className="flex flex-wrap gap-x-6 gap-y-2 text-[0.9375rem] text-fg-muted">
          <li className="inline-flex items-center gap-2">
            <Calendar className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
            {formatDateRange(event.start_date, event.end_date)}
          </li>
          <li className="inline-flex items-center gap-2">
            <PlaceIcon className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
            {place}
          </li>
          {event.specialty && <li>{event.specialty}</li>}
        </ul>
      </header>

      {event.description_excerpt && (
        <section className="space-y-2">
          <h2 className="type-h3 text-fg-strong">About this event</h2>
          <p className="type-body text-fg-muted">{event.description_excerpt}</p>
        </section>
      )}

      <LockedPanel items={LOCKED_EVENT_ITEMS} next={next} />
    </div>
  )
}
