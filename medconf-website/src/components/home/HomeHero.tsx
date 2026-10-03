// src/components/home/HomeHero.tsx
//
// Editorial hero: left-aligned, one headline, one supporting line of real
// counts, one search field, a handful of quick entries into the directory.
//
// Deliberately absent (see reports/website-audit/ux.md "AI-look removal
// list"): gradient orbs, blur/glass surfaces, gradient text, rotated
// fake-data cards, a "#1" badge, centred marketing copy.
//
// The search field is a plain GET form posting to /conferences, so it works
// with no JavaScript and needs no client component — the directory's own
// client-side filtering takes over from `?q=` once you land there.

import Link from 'next/link'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

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
    <section className="pt-10 pb-10 sm:pt-16 sm:pb-14">
      <p className="type-mono-label text-fg-subtle">Conferences · Courses · CPD</p>

      <h1 className="type-display mt-4 max-w-[26ch] text-balance text-fg-strong">
        Every medical conference, course and CPD event — in one directory.
      </h1>

      <p className="mt-5 max-w-[56ch] text-[1.0625rem] leading-relaxed text-fg-muted">
        <strong className="font-medium text-fg">{eventCount.toLocaleString('en-GB')} events</strong> listed right now,
        from {societyCount} royal colleges, faculties and international societies. Re-checked every day. Free to search,
        no account needed.
      </p>

      <form action="/conferences" method="get" role="search" className="mt-8 max-w-xl">
        <label htmlFor="home-search" className="sr-only">
          Search medical conferences, courses and CPD events
        </label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[1.125rem] -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input
              id="home-search"
              name="q"
              type="search"
              autoComplete="off"
              placeholder="Search by title, specialty or location…"
              className="h-12 pl-11 text-base md:text-base"
            />
          </div>
          <Button type="submit" size="lg" className="h-12 px-5">
            Search
          </Button>
        </div>
      </form>

      {quickEntries.length > 0 && (
        <nav aria-label="Quick entries into the directory" className="mt-5 flex flex-wrap gap-2">
          {quickEntries.map((entry) => (
            <Link
              key={entry.href}
              href={entry.href}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1 text-[0.8125rem] text-fg transition-colors duration-150 hover:border-border-strong hover:bg-surface-hover"
            >
              {entry.label}
              {entry.count !== null && <span className="type-numeric text-[0.75rem] text-fg-subtle">{entry.count}</span>}
            </Link>
          ))}
        </nav>
      )}
    </section>
  )
}
