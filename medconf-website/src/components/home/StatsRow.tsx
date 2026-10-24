// src/components/home/StatsRow.tsx
//
// Counts only — the live proof that the directory is worth signing up for.
// Every number is a facet or row count from the same fetches the page makes.

import type { HomeStats } from '@/lib/home-teaser'

export function StatsRow({ stats }: { stats: HomeStats }) {
  const items = [
    { label: 'Events listed', value: stats.events },
    { label: 'Societies', value: stats.societies },
    { label: 'Specialties', value: stats.specialties },
    { label: 'Abstract deadlines in 14 days', value: stats.closingSoon },
  ]
  return (
    <section aria-label="Directory at a glance" className="pb-20 sm:pb-24">
      <dl className="grid max-w-5xl grid-cols-2 gap-x-6 gap-y-8 border-t border-border pt-10 sm:grid-cols-4">
        {items.map((item) => (
          <div key={item.label}>
            <dt className="type-mono-label text-fg-subtle">{item.label}</dt>
            <dd className="type-numeric mt-1.5 text-[1.75rem] leading-none font-medium text-fg-strong">
              {item.value.toLocaleString('en-GB')}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
