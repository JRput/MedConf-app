// src/components/home/HowItWorks.tsx
//
// The page's one explanatory strip and its one pair of CTAs. Three statements
// of fact — including the two that are easy to get wrong about this product
// (we don't sell tickets; email alerts aren't built yet, the calendar and
// alerts are in-app) — rather than three feature boasts with gradient icon
// chips. See CLAUDE.md §5 "Email notifications: NOT implemented".

import Link from 'next/link'
import { Button } from '@/components/ui/button'

export function HowItWorks({ sourceCount }: { sourceCount: number }) {
  const points = [
    {
      title: 'Pulled daily, from the source',
      body: `Every listing is scraped from the organiser's own site — ${sourceCount} royal college, faculty and society feeds, re-checked each morning. Past events are archived, not left to rot.`,
    },
    {
      title: 'We don’t take bookings',
      body: 'MedConf has nothing to sell you. Dates, fees and CPD points are shown as published, and every event links straight out to the organiser to register.',
    },
    {
      title: 'Save events, see your year',
      body: 'A free account lets you save events to a personal calendar and get an in-app alert when something new appears in your specialty or a deadline is close.',
    },
  ]

  return (
    <section className="border-t border-border py-10 sm:py-12">
      <h2 className="type-mono-label text-fg-subtle">How MedConf works</h2>

      <div className="mt-5 grid gap-x-10 gap-y-7 sm:grid-cols-3">
        {points.map((point, i) => (
          <div key={point.title}>
            <div className="flex items-baseline gap-2.5">
              <span className="type-numeric text-[0.8125rem] text-fg-subtle">{String(i + 1).padStart(2, '0')}</span>
              <h3 className="type-h3 text-fg-strong">{point.title}</h3>
            </div>
            <p className="mt-2 text-[0.875rem] leading-relaxed text-fg-muted">{point.body}</p>
          </div>
        ))}
      </div>

      <div className="mt-9 flex flex-wrap items-center gap-3">
        <Button size="lg" asChild>
          <Link href="/auth/signup">Create a free account</Link>
        </Button>
        <Button size="lg" variant="outline" asChild>
          <Link href="/conferences">Browse the directory</Link>
        </Button>
      </div>
    </section>
  )
}
