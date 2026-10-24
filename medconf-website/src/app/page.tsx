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
import { daysUntil, formatDateRange } from '@/lib/format'
import { SPECIALTY_PARENTS, canonicalSpecialty } from '@/lib/taxonomy/specialties'
import { societyInfo } from '@/lib/taxonomy/societies'
import type { DirectoryEvent } from '@/lib/directory'
import { HomeHero, type QuickEntry } from '@/components/home/HomeHero'
import { HomeSection } from '@/components/home/HomeSection'
import { TeaserRows, type TeaserRow } from '@/components/home/TeaserRows'
import { StatsRow } from '@/components/home/StatsRow'
import { GateProvider } from '@/components/auth/GateProvider'
import { TeaserBlur } from '@/components/auth/TeaserBlur'
import { CLOSING_SOON_DAYS, homeStats, pickSocieties, relativeDaysLeft, relativeDeadline, splitTeaser, sumByParent } from '@/lib/home-teaser'
import { fetchHomePreview, type HomePreview } from '@/lib/preview'
import { BrowseTiles, type BrowseTile } from '@/components/home/BrowseTiles'
import { HowItWorks } from '@/components/home/HowItWorks'

export const revalidate = 3600

export const metadata = {
  title: 'MedConf — medical conferences, courses and CPD in one directory',
  description:
    'Search medical conferences, courses and CPD events from royal colleges, faculties and international societies. Create a free account to search the full directory by specialty, date, format, price and society.',
}

/** How many featured society tiles the "Browse by society" band shows. */
const FEATURED_SOCIETIES = ['RCGP', 'RCP', 'RCSEng', 'RCPsych', 'ESMO', 'ASCO', 'RCPCH', 'RSM']

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

/** Everything the page renders, independent of where it was read from. */
interface HomeData {
  usedFixture: boolean
  eventCount: number
  societyCount: number
  societyCounts: Record<string, number>
  specialtyCounts: Record<string, number>
  onlineThisMonth: number
  freeCount: number | null
  closingTeaser: TeaserRow[]
  closingWithin14: number
  monthTeaser: TeaserRow[]
  monthTotal: number
  deadlineStat: number
}

const societyName = (code: string | null) => (code ? (societyInfo(code)?.name ?? code) : null)

/** Anonymous path: three narrow database functions, no table reads. */
function fromPreview(p: HomePreview): HomeData {
  const specialtyCounts = sumByParent(p.specialties, (raw) => canonicalSpecialty(raw === 'unspecified' ? null : raw).parent)
  const societyCounts = Object.fromEntries(p.societies.map((x) => [x.society, x.count]))
  return {
    usedFixture: false,
    eventCount: p.counts.events,
    societyCount: p.counts.societies,
    societyCounts,
    specialtyCounts,
    onlineThisMonth: p.counts.online_this_month,
    freeCount: null, // the preview carries no price facet; the chip shows no count
    closingTeaser: p.closing_soon.flatMap((e) => {
      const meta = relativeDaysLeft(e.days_left)
      return meta ? [{ id: e.id, name: e.name, society: societyName(e.society), meta }] : []
    }),
    closingWithin14: p.counts.closing_soon,
    monthTeaser: p.this_month.map((e) => ({
      id: e.id,
      name: e.name,
      society: societyName(e.society),
      meta: formatDateRange(e.start_date, e.end_date),
    })),
    monthTotal: p.counts.this_month,
    deadlineStat: p.counts.closing_soon,
  }
}

// TODO(access-gate): remove after Phase 2b is applied — direct reads are the
// fallback for a database where home_preview() does not exist yet.
async function fromDirectReads(supabase: ReturnType<typeof createServerClient>): Promise<HomeData> {
  const opts = { fixture: false, wantFacets: false }
  const [overview, thisMonth, abstractsOpen, onlineThisMonth] = await Promise.all([
    // pageSize 1 — we want `total` and the facet counts, not rows.
    resolveDirectory(supabase, { pageSize: 1 }, { fixture: false, wantFacets: true }),
    resolveDirectory(supabase, { datePreset: 'this-month', pageSize: 12 }, opts),
    // Only ~55 events have abstracts open at any time (data.md §1), so one
    // page covers the lot; the 14-day window and the deadline sort are then
    // applied here rather than in SQL.
    resolveDirectory(supabase, { abstractsOpen: true, pageSize: 100 }, opts),
    resolveDirectory(supabase, { datePreset: 'this-month', format: ['online'], pageSize: 1 }, opts),
  ])

  const facets = overview.facets
  const societyCounts = facets?.society ?? {}
  const closingSoon = sortByDeadline(abstractsOpen.page.rows)
  const closingWithin14 = closingSoon.filter((e) => {
    const d = daysUntil(e.abstractDeadline)
    return d !== null && d >= 0 && d <= CLOSING_SOON_DAYS
  })
  // Prefer genuinely-urgent rows; if none are inside the window today, fall
  // back to the next deadlines rather than showing an empty band.
  const closingRows = (closingWithin14.length ? closingWithin14 : closingSoon).slice(0, 5)
  const today = new Date()

  return {
    usedFixture: overview.usedFixture,
    eventCount: overview.page.total,
    societyCount: Object.keys(societyCounts).length,
    societyCounts,
    specialtyCounts: facets?.specialty ?? {},
    onlineThisMonth: onlineThisMonth.page.total,
    freeCount: facets?.priceBucket.free ?? null,
    closingTeaser: closingRows.flatMap((e) => {
      const meta = relativeDeadline(e.abstractDeadline, today)
      return meta ? [{ id: e.id, name: e.name, society: societyName(e.society), meta }] : []
    }),
    closingWithin14: closingWithin14.length,
    monthTeaser: thisMonth.page.rows.map((e) => ({
      id: e.id,
      name: e.name,
      society: societyName(e.society),
      meta: formatDateRange(e.startDate, e.endDate),
    })),
    monthTotal: thisMonth.page.total,
    deadlineStat: homeStats({
      total: 0,
      societyCounts: {},
      specialtyCounts: {},
      deadlines: abstractsOpen.page.rows.map((e) => e.abstractDeadline),
      today,
      windowDays: CLOSING_SOON_DAYS,
    }).closingSoon,
  }
}

export default async function HomePage() {
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  )

  const [preview, sourceCount] = await Promise.all([fetchHomePreview(supabase), countSources(supabase)])
  // Everything below is reduced to plain strings on the server, so a fee, CPD
  // value or exact deadline cannot reach the anonymous HTML or RSC payload.
  const data = preview ? fromPreview(preview) : await fromDirectReads(supabase)

  const { usedFixture, eventCount, societyCount, societyCounts, specialtyCounts, closingTeaser, closingWithin14 } = data

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
      count: data.onlineThisMonth || null,
    },
    { label: 'Free', href: '/conferences?price=free', count: data.freeCount },
  ]

  const specialtyTiles: BrowseTile[] = rankedSpecialties.slice(0, 12).map((p) => ({
    label: p.label,
    href: `/conferences?specialty=${encodeURIComponent(p.slug)}`,
    count: specialtyCounts[p.slug] ?? 0,
  }))

  const societyTiles: BrowseTile[] = pickSocieties(
    Object.entries(societyCounts).map(([society, count]) => ({ society, count })),
    { featured: FEATURED_SOCIETIES, limit: 8 }
  ).map(({ society, count }) => ({
    label: society,
    sub: societyInfo(society)?.name,
    href: `/conferences?society=${encodeURIComponent(society)}`,
    count,
  }))

  const { visible: monthVisible, blurred: monthBlurred } = splitTeaser(data.monthTeaser, 6)
  const monthTotal = data.monthTotal

  const stats = {
    events: eventCount,
    societies: societyCount,
    specialties: rankedSpecialties.length,
    closingSoon: data.deadlineStat,
  }

  return (
    <GateProvider>
      <div className="mx-auto max-w-[1180px] px-4 pb-8 sm:px-6">
        {usedFixture && (
          <p className="type-mono-label pt-4 text-warn-text">
            Showing sample data — live counts will appear once the database is reachable.
          </p>
        )}

        <HomeHero eventCount={eventCount} societyCount={societyCount} quickEntries={quickEntries} />

        <StatsRow stats={stats} />

        {closingTeaser.length > 0 && (
          <HomeSection
            title="Closing soon"
            note={
              closingWithin14
                ? `${closingWithin14} abstract deadline${closingWithin14 === 1 ? '' : 's'} within ${CLOSING_SOON_DAYS} days`
                : 'Next abstract deadlines'
            }
            link={{ href: '/conferences?abstractsOpen=1', label: 'All with abstracts open' }}
          >
            <TeaserRows rows={closingTeaser} />
          </HomeSection>
        )}

        {monthVisible.length > 0 && (
          <HomeSection
            title="This month"
            note={`${monthTotal.toLocaleString('en-GB')} events running or starting before the end of the month`}
            link={{ href: '/conferences?datePreset=this-month', label: 'All this month' }}
          >
            <TeaserRows rows={monthVisible} />
            {monthBlurred.length > 0 && (
              <div className="mt-2.5">
                <TeaserBlur total={monthTotal} next="/conferences?datePreset=this-month">
                  <TeaserRows rows={monthBlurred} />
                </TeaserBlur>
              </div>
            )}
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
    </GateProvider>
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
async function countSources(supabase: ReturnType<typeof createServerClient>): Promise<number | null> {
  try {
    const { count, error } = await supabase.from('scraper_sources').select('id', { count: 'exact', head: true }).eq('active', true)
    if (error) throw error
    return count ?? null
  } catch {
    return null
  }
}
