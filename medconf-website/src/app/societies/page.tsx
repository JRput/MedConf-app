// src/app/societies/page.tsx
// "Browse by society" — the replacement for the old 44-pill source wall (see
// ../../../../reports/website-audit/ux.md #2). Grid of tiles grouped by kind
// (Royal Colleges & Faculties / International societies / Specialist
// societies / Medical defence), each linking into the directory pre-filtered
// to that society.

import Link from 'next/link'
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { ArrowRight, Building2, Globe2, Shield, Stethoscope } from 'lucide-react'
import { resolveDirectory, getSocietyNextDates, wantsFixture } from '@/lib/directory-source'
import { societiesByKind, type SocietyKind } from '@/lib/taxonomy/societies'
import { formatDateRange } from '@/lib/format'

export const metadata = {
  title: 'Societies — MedConf',
  description: 'Browse medical conferences and CPD by royal college, faculty, specialist society or international congress.',
}

const KIND_META: Record<SocietyKind, { label: string; Icon: typeof Building2 }> = {
  'royal-college': { label: 'Royal Colleges & Faculties', Icon: Building2 },
  faculty: { label: 'Royal Colleges & Faculties', Icon: Building2 },
  specialist: { label: 'Specialist societies', Icon: Stethoscope },
  international: { label: 'International societies', Icon: Globe2 },
  defence: { label: 'Medical defence', Icon: Shield },
  other: { label: 'Other', Icon: Building2 },
}
const KIND_ORDER: SocietyKind[] = ['royal-college', 'international', 'specialist', 'defence', 'other']

export default async function SocietiesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const rawParams = await searchParams
  const urlParams = new URLSearchParams()
  for (const [key, value] of Object.entries(rawParams)) {
    if (value != null) urlParams.set(key, Array.isArray(value) ? value.join(',') : value)
  }
  const fixture = wantsFixture(urlParams)

  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => cookieStore.getAll(), setAll: () => {} } }
  )

  const [{ facets, usedFixture }, nextDates] = await Promise.all([
    resolveDirectory(supabase, {}, { fixture, wantFacets: true }),
    getSocietyNextDates(supabase, { fixture }),
  ])

  const grouped = societiesByKind()

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-20 sm:px-6">
      <header className="border-b border-border py-6">
        <h1 className="type-h1 text-fg-strong">Browse by society</h1>
        <p className="mt-1.5 max-w-2xl text-[0.8125rem] text-fg-muted">
          Every royal college, faculty, specialist society and international congress MedConf tracks. Pick one to see
          just its events.
        </p>
        {usedFixture && <p className="mt-2 type-mono-label text-warn-text">Showing sample data — live counts will appear once connected.</p>}
      </header>

      <div className="space-y-10 pt-8">
        {KIND_ORDER.filter((kind) => grouped[kind]?.length).map((kind) => {
          const { label, Icon } = KIND_META[kind]
          // 'faculty' folds into the same heading as 'royal-college' — skip a duplicate section.
          if (kind === 'faculty') return null
          const list = kind === 'royal-college' ? [...grouped['royal-college'], ...grouped.faculty].sort((a, b) => a.name.localeCompare(b.name)) : grouped[kind]

          return (
            <section key={kind}>
              <h2 className="type-mono-label mb-3 flex items-center gap-2 text-fg-subtle">
                <Icon className="size-4" aria-hidden />
                {label}
                <span className="text-fg-subtle">· {list.length}</span>
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {list.map((s) => {
                  const count = facets?.society[s.short] ?? 0
                  const next = nextDates[s.short]
                  return (
                    <Link
                      key={s.short}
                      href={`/conferences?society=${encodeURIComponent(s.short)}`}
                      className="group flex flex-col gap-2 rounded-lg border border-border bg-surface p-4 transition-colors duration-150 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="text-[0.9375rem] font-medium leading-snug text-fg-strong">{s.name}</h3>
                        <ArrowRight className="size-4 shrink-0 text-fg-subtle transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-brand-text" aria-hidden />
                      </div>
                      <p className="type-mono-label text-fg-subtle">{s.country}</p>
                      <p className="mt-auto text-[0.8125rem] text-fg-muted">
                        {count} upcoming event{count === 1 ? '' : 's'}
                        {next && <span> · next {formatDateRange(next, null)}</span>}
                      </p>
                    </Link>
                  )
                })}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
