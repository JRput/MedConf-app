// src/components/home/HomeHero.tsx
//
// Editorial hero: left-aligned, one headline, one plain value sentence, the
// search box (the call to action), and a handful of quick entries. The search
// box and chips are client islands that open the sign-in gate for signed-out
// visitors; the HTML around them is static.
//
// Deliberately absent (see reports/website-audit/ux.md "AI-look removal
// list"): gradient orbs, blur/glass surfaces, gradient text, rotated
// fake-data cards, a "#1" badge, centred marketing copy.

import { GatedLink } from '@/components/auth/GatedLink'
import { GatedSearchForm } from './GatedSearchForm'

export interface QuickEntry {
  label: string
  href: string
  count: number | null
}

export function HomeHero({
  eventCount,
  societyCount,
  quickEntries,
}: {
  eventCount: number
  societyCount: number
  quickEntries: QuickEntry[]
}) {
  return (
    <section className="pt-16 pb-16 sm:pt-24 sm:pb-20">
      <div className="max-w-5xl">
        <p className="type-mono-label text-fg-subtle">Conferences · Courses · CPD</p>

        <h1 className="type-display mt-4 max-w-[26ch] text-balance text-fg-strong">
          Every medical conference, course and CPD event — in one directory.
        </h1>

        <p className="mt-5 max-w-[56ch] text-[1.0625rem] leading-relaxed text-fg-muted">
          <strong className="font-medium text-fg">{eventCount.toLocaleString('en-GB')} events</strong> from{' '}
          {societyCount} royal colleges, faculties and international societies, re-checked every day. A free account
          unlocks search, fees, CPD points and abstract deadlines.
        </p>

        <GatedSearchForm />

        {quickEntries.length > 0 && (
          <nav aria-label="Quick entries into the directory" className="mt-5 flex flex-wrap gap-2">
            {quickEntries.map((entry) => (
              <GatedLink
                key={entry.href}
                href={entry.href}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1 text-[0.8125rem] text-fg transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-ring [@media(hover:hover)_and_(pointer:fine)]:hover:border-border-strong [@media(hover:hover)_and_(pointer:fine)]:hover:bg-surface-hover"
              >
                {entry.label}
                {entry.count !== null && <span className="type-numeric text-[0.75rem] text-fg-subtle">{entry.count}</span>}
              </GatedLink>
            ))}
          </nav>
        )}
      </div>
    </section>
  )
}
