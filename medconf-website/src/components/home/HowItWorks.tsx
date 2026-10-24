// src/components/home/HowItWorks.tsx
//
// The page's one explanatory strip and its one pair of CTAs. Three statements
// of fact, including the two that are easy to get wrong about this product
// (we don't sell tickets; email alerts aren't built yet, alerts are in-app).
// Step 1 is the account: the directory is for registered users. See
// CLAUDE.md §5 "Email notifications: NOT implemented".

import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { PRESS } from '@/components/community/press'
import { signInHref, signUpHref } from '@/lib/auth/urls'

export function HowItWorks({ sourceCount }: { sourceCount: number | null }) {
  const points = [
    {
      title: 'Create a free account',
      body: 'Registered users search the full directory, see fees, CPD points and abstract deadlines, save events to a personal calendar and get in-app alerts for their specialty.',
    },
    {
      title: 'Pulled daily, from the source',
      body: `Every listing is scraped from the organiser's own site, across ${sourceCount ? `${sourceCount} active` : 'our registered'} royal college, faculty and society feeds, re-checked each morning. Past events are archived, not left to rot.`,
    },
    {
      title: 'We don’t take bookings',
      body: 'MedConf has nothing to sell you. Details are shown as the organiser published them, and every event links straight out to the organiser to register.',
    },
  ]

  return (
    <section className="border-t border-border py-20 sm:py-24">
      <div className="max-w-5xl">
        <h2 className="type-mono-label text-fg-subtle">How MedConf works</h2>

        <div className="mt-6 grid gap-x-10 gap-y-8 sm:grid-cols-3">
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

        <div className="mt-10 flex flex-wrap items-center gap-3">
          <Button size="lg" className={PRESS} asChild>
            <Link href={signUpHref()}>Create a free account</Link>
          </Button>
          <Button size="lg" variant="outline" className={PRESS} asChild>
            <Link href={signInHref()}>Sign in</Link>
          </Button>
        </div>
      </div>
    </section>
  )
}
