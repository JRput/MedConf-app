import type { Conference, PricingTier } from '@/lib/types'

/** schema.org Event JSON-LD for search engines — dates, location, offers. */
export function EventJsonLd({ conference, tiers }: { conference: Conference; tiers: PricingTier[] }) {
  const c = conference
  const prices = tiers.map((t) => Number(t.price_gbp)).filter((n) => Number.isFinite(n))
  const priceMin = prices.length ? Math.min(...prices) : undefined
  const currency = tiers.find((t) => t.currency)?.currency ?? 'GBP'

  const location =
    c.event_format === 'online'
      ? { '@type': 'VirtualLocation', url: c.organiser_url ?? undefined }
      : {
          '@type': 'Place',
          name: c.venue_name ?? c.city ?? undefined,
          address: [c.city, c.region].filter(Boolean).join(', ') || undefined,
        }

  const json = {
    '@context': 'https://schema.org',
    '@type': 'Event',
    name: c.conference_name,
    description: c.description ?? undefined,
    startDate: c.start_date ?? undefined,
    endDate: c.end_date ?? c.start_date ?? undefined,
    eventAttendanceMode:
      c.event_format === 'online'
        ? 'https://schema.org/OnlineEventAttendanceMode'
        : c.event_format === 'hybrid'
          ? 'https://schema.org/MixedEventAttendanceMode'
          : 'https://schema.org/OfflineEventAttendanceMode',
    eventStatus: c.is_sold_out
      ? 'https://schema.org/EventMovedOnline'
      : 'https://schema.org/EventScheduled',
    location,
    offers:
      priceMin !== undefined
        ? {
            '@type': 'Offer',
            price: priceMin,
            priceCurrency: currency,
            url: c.organiser_url ?? c.booking_url ?? undefined,
            availability: c.is_sold_out ? 'https://schema.org/SoldOut' : 'https://schema.org/InStock',
          }
        : undefined,
  }

  // JSON.stringify output could contain a literal "</script>" if a scraped
  // title/description ever included it, which would break out of the tag —
  // escape forward slashes in that sequence so the payload stays inert.
  const safeJson = JSON.stringify(json).replace(/<\/script/gi, '<\\/script')

  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJson }} />

}
