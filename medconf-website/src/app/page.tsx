// src/app/page.tsx
//
// The homepage. A separate surface from the directory (owner's W5 decision),
// but built from the directory's own data and primitives so nothing on it is
// decorative or invented: every number comes from queryFacets/queryDirectory
// at render time, and every row is a real event you can click through to.
//
// What this replaced (see reports/website-audit/ux.md #5 and its "AI-look
// removal list"): two blur-3xl gradient orbs, a cyan→teal .gradient-text
// headline, three rotated "floating" cards containing fabricated events, a
// "UK's #1 Medical Conference Directory" badge, gradient CTA buttons with
// colour-matched glow shadows, a fake filter-panel mock-up, and centred
// marketing copy throughout.
//
// Server component with ISR: directory data moves on a daily cron (02:00 UTC
// scrape, 04:00 UTC remediator — see CLAUDE.md §3), so an hourly revalidate is
// generous and means no spinner and no skeleton: the page is HTML by the time
// it reaches the browser.

import { createServerClient } from '@supabase/ssr'
import { resolveDirectory } from '@/lib/directory-source'
import { daysUntil } from '@/lib/format'
import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'
import { societyInfo } from '@/lib/taxonomy/societies'
import type { DirectoryEvent } from '@/lib/directory'
import { HomeHero, type QuickEntry } from '@/components/home/HomeHero'
import { HomeSection } from '@/components/home/HomeSection'
import { HomeEventList } from '@/components/home/HomeEventList'
import { BrowseTiles, type BrowseTile } from '@/components/home/BrowseTiles'
import { HowItWorks } from '@/components/home/HowItWorks'

export const revalidate = 3600

export const metadata = {
  title: 'MedConf — medical conferences, courses and CPD in one directory',
  description:
    'Search medical conferences, courses and CPD events from royal colleges, faculties and international societies. Filter by specialty, date, format, price and society. Free, no account needed.',
}

/** How many featured society tiles the "Browse by society" band shows. */
const FEATURED_SOCIETIES = ['RCGP', 'RCP', 'RCSEng', 'RCPsych', 'ESMO', 'ASCO', 'RCPCH', 'RSM']
/** Deadline horizon for "Closing soon" — matches DeadlineBadge's urgency bands. */
const CLOSING_SOON_DAYS = 14

/**
 * Hero-chip labels for the handful of taxonomy parents whose full label is a
 * mouthful in a 390px-wide chip row. Same slug, same filter, shorter name —
 * the full label is still what the "Browse by specialty" tiles and the
 * directory's own filter panel show, so nothing is being renamed, only
 * abbreviated in the one place width is scarce.
 */
const CHIP_LABEL: Record<string, string> = {
  'leadership-management': 'Leadership & Management',
  'obgyn-womens-health': 'Obstetrics & Gynaecology',
  'msk-trauma-orthopaedics': 'Trauma & Orthopaedics',
  'pathology-laboratory-medicine': 'Pathology',
  'anaesthetics-critical-care': 'Anaesthetics & ICU',
  'medicine-general': 'Internal Medicine',
  'surgery-general': 'General Surgery',
  'psychiatry-mental-health': 'Psychiatry',
  'medical-education': 'Medical Education',
  'radiology-imaging': 'Radiology',
}

export default async function HomePage() {
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  )

  const opts = { fixture: false, wantFacets: false }

  const [overview, thisMonth, abstractsOpen, onlineThisMonth, sourceCount] = await Promise.all([
    // pageSize 1 — we want `total` and the facet counts, not rows.
    resolveDirectory(supabase, { pageSize: 1 }, { fixture: false, wantFacets: true }),
    resolveDirectory(supabase, { datePreset: 'this-month', pageSize: 6 }, opts),
    // Only ~55 events have abstracts open at any time (data.md §1), so one
    // page covers the lot; the 14-day window and the deadline sort are then
    // applied here rather than in SQL, since queryDirectory's `sort` has no
    // abstract_deadline option and adding one for a single homepage band
    // would be the wrong place to put it.
    resolveDirectory(supabase, { abstractsOpen: true, pageSize: 100 }, opts),
    resolveDirectory(supabase, { datePreset: 'this-month', format: ['online'], pageSize: 1 }, opts),
    countSources(supabase),
  ])

  const facets = overview.facets
  const eventCount = overview.page.total
  const societyCounts = facets?.society ?? {}
  const societyCount = Object.keys(societyCounts).length

  const closingSoon = sortByDeadline(abstractsOpen.page.rows)
  const closingWithin14 = closingSoon.filter((e) => {
    const d = daysUntil(e.abstractDeadline)
    return d !== null && d >= 0 && d <= CLOSING_SOON_DAYS
  })
  // Prefer genuinely-urgent rows; if none are inside the window today, fall
  // back to the next deadlines rather than showing an empty band — the badge
  // on each row still states the real urgency either way.
  const closingRows = (closingWithin14.length ? closingWithin14 : closingSoon).slice(0, 5)

  const specialtyCounts = facets?.specialty ?? {}
  const rankedSpecialties = SPECIALTY_PARENTS.filter((p) => p.slug !== 'other' && (specialtyCounts[p.slug] ?? 0) > 0).sort(
    (a, b) => (specialtyCounts[b.slug] ?? 0) - (specialtyCounts[a.slug] ?? 0)
  )

  const quickEntries: QuickEntry[] = [
    ...rankedSpecialties.slice(0, 4).map((p) => ({
      label: CHIP_LABEL[p.slug] ?? p.label,
      href: `/conferences?specialty=${encodeURIComponent(p.slug)}`,
      count: specialtyCounts[p.slug] ?? null,
    })),
    {
      label: 'Online this month',
      href: '/conferences?datePreset=this-month&format=online',
      count: onlineThisMonth.page.total || null,
    },
    { label: 'Free', href: '/conferences?price=free', count: facets?.priceBucket.free ?? null },
  ]

  const specialtyTiles: BrowseTile[] = rankedSpecialties.slice(0, 12).map((p) => ({
    label: p.label,
    href: `/conferences?specialty=${encodeURIComponent(p.slug)}`,
    count: specialtyCounts[p.slug] ?? 0,
  }))

  const societyTiles: BrowseTile[] = FEATURED_SOCIETIES.filter((short) => (societyCounts[short] ?? 0) > 0).map((short) => ({
    label: short,
    sub: societyInfo(short)?.name,
    href: `/conferences?society=${encodeURIComponent(short)}`,
    count: societyCounts[short] ?? 0,
  }))

  const usedFixture = overview.usedFixture

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-20 sm:px-6">
      {usedFixture && (
        <p className="type-mono-label pt-4 text-warn-text">
          Showing sample data — live counts will appear once the database is reachable.
        </p>
      )}

      <HomeHero eventCount={eventCount} societyCount={societyCount} quickEntries={quickEntries} />

      {closingRows.length > 0 && (
        <HomeSection
          title="Closing soon"
          note={
            closingWithin14.length
              ? `${closingWithin14.length} abstract deadline${closingWithin14.length === 1 ? '' : 's'} within ${CLOSING_SOON_DAYS} days`
              : 'Next abstract deadlines'
          }
          link={{ href: '/conferences?abstractsOpen=1', label: 'All with abstracts open' }}
        >
          <HomeEventList events={closingRows} societyCounts={societyCounts} />
        </HomeSection>
      )}

      {thisMonth.page.rows.length > 0 && (
        <HomeSection
          title="This month"
          note={`${thisMonth.page.total.toLocaleString('en-GB')} events running or starting before the end of the month`}
          link={{ href: '/conferences?datePreset=this-month', label: 'All this month' }}
        >
          <HomeEventList events={thisMonth.page.rows} societyCounts={societyCounts} />
        </HomeSection>
      )}

      {specialtyTiles.length > 0 && (
        <HomeSection title="Browse by specialty" link={{ href: '/conferences', label: 'All specialties' }}>
          <BrowseTiles tiles={specialtyTiles} />
        </HomeSection>
      )}

      {societyTiles.length > 0 && (
        <HomeSection
          title="Browse by society"
          note={`${societyCount} societies with events listed`}
          link={{ href: '/societies', label: 'All societies' }}
        >
          <BrowseTiles tiles={societyTiles} />
        </HomeSection>
      )}

      <HowItWorks sourceCount={sourceCount} />
    </div>
  )
}

/** Soonest abstract deadline first; rows with no published deadline last. */
function sortByDeadline(rows: DirectoryEvent[]): DirectoryEvent[] {
  return [...rows].sort((a, b) => {
    if (a.abstractDeadline && b.abstractDeadline) return a.abstractDeadline.localeCompare(b.abstractDeadline)
    if (a.abstractDeadline) return -1
    if (b.abstractDeadline) return 1
    return 0
  })
}

/**
 * How many organiser feeds the scraper tracks — the one number on this page
 * that isn't a directory facet. `scraper_sources` has a public-read RLS
 * policy (supabase_schema.sql), so the anon key can count it. If that ever
 * changes, fall back to the figure in reports/website-audit/data.md rather
 * than failing the page render.
 */
async function countSources(supabase: ReturnType<typeof createServerClient>): Promise<number> {
  try {
    const { count, error } = await supabase.from('scraper_sources').select('id', { count: 'exact', head: true })
    if (error) throw error
    return count ?? 45
  } catch {
    return 45
  }
}
