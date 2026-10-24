// src/app/conferences/[id]/page.tsx
// Server-rendered — public and indexable, so metadata/JSON-LD need real
// HTML on first response rather than a client-side fetch. Interactive bits
// (save, calendar, share, reminders) live in client components underneath.

import { cache } from 'react'
import { cookies } from 'next/headers'
import { notFound } from 'next/navigation'
import { createServerClient } from '@supabase/ssr'
import type { SupabaseClient } from '@supabase/supabase-js'
import Link from 'next/link'
import type { Metadata } from 'next'
import { createSupabaseServerClient } from '@/lib/supabase-server'
import { resolveDirectory, wantsFixture } from '@/lib/directory-source'
import { expandSpecialtyFilter, type DirectoryFilters } from '@/lib/directory-query'
import { canonicalSpecialty } from '@/lib/taxonomy/specialties'
import type { Conference, PricingTier, CourseSession, SourceSummary } from '@/lib/types'
import type { CommunityFact, CommunityTier } from '@/lib/community/types'
import { overlayConference, pickTiers } from '@/lib/community/overlay'
import { hasAbstractInfo } from '@/lib/conference-helpers'
import { formatDateRange } from '@/lib/format'
import { excerpt, publicEventFields, type PublicEventFields } from '@/lib/event-public'
import { fetchEventPreview } from '@/lib/preview'
import { EventTeaser } from '@/components/event/EventTeaser'

import { Breadcrumb } from '@/components/event/Breadcrumb'
import { EventSidebar } from '@/components/event/EventSidebar'
import { AbstractsBlock } from '@/components/event/AbstractsBlock'
import { OrganiserBlock } from '@/components/event/OrganiserBlock'
import { RelatedEvents } from '@/components/event/RelatedEvents'
import { EventJsonLd } from '@/components/event/EventJsonLd'
import { EventTypeBadge } from '@/components/domain/EventTypeBadge'
import { FormatBadge } from '@/components/domain/FormatBadge'
import { SocietyChip } from '@/components/domain/SocietyChip'
import { PricingTable } from '@/components/conferences/PricingTable'
import { SessionsTable } from '@/components/conferences/SessionsTable'
import { ReminderPanel } from '@/components/conferences/ReminderPanel'
import { CommunityNotes } from '@/components/community/CommunityNotes'
import { AddInfoTrigger } from '@/components/community/AddInfoTrigger'

/**
 * `full: false` (anonymous render and metadata) fetches the conference row and
 * its society only. Pricing, sessions and community data are not even
 * requested, so there is nothing to leak into the anonymous tree.
 */
/** One cookieless client per request, so generateMetadata and the page share a cached preview call. */
const anonClient = cache(() => createSupabaseServerClient())

async function fetchConferenceData(id: number, supabase: SupabaseClient = createSupabaseServerClient(), full = true) {
  const [confResp, pricingResp, sessionsResp] = await Promise.all([
    supabase.from('conferences').select('*').eq('id', id).eq('archived', false).single(),
    full ? supabase.from('pricing_tiers').select('*').eq('conference_id', id) : Promise.resolve({ data: [] }),
    full
      ? supabase.from('course_sessions').select('*').eq('course_id', id).order('start_date', { ascending: true })
      : Promise.resolve({ data: [] }),
  ])

  if (!confResp.data) return null

  const conference = confResp.data as Conference
  const tiers = (pricingResp.data ?? []) as PricingTier[]
  const sessions = (sessionsResp.data ?? []) as CourseSession[]

  let society: SourceSummary['society'] = null
  if (conference.source_id) {
    const { data } = await supabase
      .from('scraper_sources')
      .select('society')
      .eq('id', conference.source_id)
      .single()
    society = data?.society ?? null
  }

  // Community layer: published facts/tiers only (RLS exposes nothing else to
  // anon, and we filter explicitly). A missing table or any error must never
  // break the page, so failures degrade to "no community data".
  let facts: CommunityFact[] = []
  let communityTiers: CommunityTier[] = []
  if (full) try {
    const [f, t] = await Promise.all([
      supabase.from('community_facts').select('*').eq('conference_id', id).eq('is_published', true),
      supabase.from('community_tiers').select('*').eq('conference_id', id).eq('is_published', true),
    ])
    if (!f.error) facts = (f.data ?? []) as CommunityFact[]
    if (!t.error) communityTiers = (t.data ?? []) as CommunityTier[]
  } catch {
    // ignore
  }

  return { conference, tiers, sessions, society, facts, communityTiers }
}

async function fetchRelatedEvents(conference: Conference, supabase: SupabaseClient) {
  if (!conference.start_date) return []

  const { parent } = canonicalSpecialty(conference.specialty)
  const rawSpecialty = expandSpecialtyFilter([parent])
  if (rawSpecialty.length === 0) return []

  const start = new Date(conference.start_date)
  const from = new Date(start)
  from.setDate(from.getDate() - 45)
  const to = new Date(start)
  to.setDate(to.getDate() + 45)
  const iso = (d: Date) => d.toISOString().slice(0, 10)

  const filters: Partial<DirectoryFilters> = {
    specialty: [parent],
    dateFrom: iso(from),
    dateTo: iso(to),
    sort: 'date',
    page: 1,
    pageSize: 5,
  }

  try {
    const { page } = await resolveDirectory(supabase, filters, { fixture: wantsFixture(new URLSearchParams()), wantFacets: false })
    return page.rows.filter((r) => r.id !== conference.id).slice(0, 4)
  } catch (err) {
    console.error('[conferences/[id]] related events query failed', err)
    return []
  }
}

function metadataFor(c: { conference_name: string; description: string | null; start_date: string | null; end_date: string | null; event_format: Conference['event_format']; city: string | null; region: string | null }): Metadata {
  const when = formatDateRange(c.start_date, c.end_date)
  const where = c.event_format === 'online' ? 'Online' : [c.city, c.region].filter(Boolean).join(', ')
  const description =
    c.description?.slice(0, 160) ??
    [c.conference_name, when, where].filter(Boolean).join(' · ')

  return {
    title: `${c.conference_name} — MedConf`,
    description,
    openGraph: {
      title: c.conference_name,
      description,
      type: 'website',
    },
    twitter: {
      card: 'summary',
      title: c.conference_name,
      description,
    },
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params
  // Public fields only, through the narrow function (works after anonymous
  // table reads are revoked). Falls back to the direct read while the
  // function is missing.
  const preview = await fetchEventPreview(anonClient(), Number(id))
  if (preview.status === 'not_found') return { title: 'Event not found — MedConf' }
  if (preview.status === 'error') return { title: 'MedConf' } // the page itself throws; no data here
  if (preview.status === 'ok') return metadataFor({ ...preview.data, description: preview.data.description_excerpt })

  // TODO(access-gate): remove after Phase 2b is applied
  const data = await fetchConferenceData(Number(id), undefined, false)
  if (!data) return { title: 'Event not found — MedConf' }
  return metadataFor(data.conference)
}

function renderTeaser(pub: PublicEventFields) {
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-bg">
      <div className="mx-auto max-w-[1180px] px-4 py-6 sm:px-6 sm:py-10">
        <Breadcrumb specialty={pub.specialty} title={pub.conference_name} anonymous />
        <div className="mt-6">
          <EventTeaser event={pub} />
        </div>
        <div className="mt-10 border-t border-border-subtle pt-4">
          <Link href="/" className="type-small text-fg-muted hover:text-brand-text">
            ← Back to home
          </Link>
        </div>
      </div>
      <EventJsonLd
        anonymous
        conference={{
          conference_name: pub.conference_name,
          description: pub.description_excerpt,
          start_date: pub.start_date,
          end_date: pub.end_date,
          event_format: pub.event_format,
          is_sold_out: false,
          city: pub.city,
          region: pub.region,
        }}
      />
    </div>
  )
}

export default async function ConferenceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  // Cookie-aware client so the session (and RLS) is the visitor's own. The
  // page is dynamic because of this; the anonymous branch below is the
  // teaser and is built only from publicEventFields().
  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => cookieStore.getAll(), setAll: () => {} } }
  )
  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser()
  // A real failure (not just "no session") means a signed-in visitor may be
  // served the teaser; leave a trace without logging the token or user.
  if (userError && userError.name !== 'AuthSessionMissingError') {
    console.warn('[gate] getUser failed', userError.status, userError.name)
  }

  // Anonymous: read only the public fields, through the narrow function.
  // null means the function is missing (fall back to the direct read below).
  let pub: PublicEventFields | null = null
  if (!user) {
    const preview = await fetchEventPreview(anonClient(), Number(id))
    if (preview.status === 'not_found') notFound()
    // A real error (not "function missing") must not fall back to table reads
    // or render an empty teaser: throw to Next's error boundary.
    if (preview.status === 'error') throw new Error('event_preview failed')
    if (preview.status === 'ok') {
      // The SQL excerpt is a plain 300-character cut; re-trim at a word boundary with an ellipsis.
      const d = preview.data.description_excerpt
      pub = { ...preview.data, description_excerpt: d && d.length >= 300 ? excerpt(d, 299) : excerpt(d) }
    }
  }

  // TODO(access-gate): the direct-read branch for anonymous visitors goes
  // away after Phase 2b; signed-in visitors always take it.
  const data = pub ? null : await fetchConferenceData(Number(id), supabase, !!user)
  if (!pub && !data) notFound()

  if (!user) {
    if (!pub) pub = publicEventFields(data!.conference, data!.society)
    return renderTeaser(pub)
  }
  if (!data) notFound()
  const { conference: scraped, tiers: scrapedTiers, sessions, society, facts, communityTiers } = data
  // Scraped data always wins; community values only fill what is empty.
  const { conference: c, communityFields } = overlayConference(scraped, facts)
  const tiers = pickTiers(scrapedTiers, communityTiers)
  const communityFieldList = [...communityFields]
  const related = await fetchRelatedEvents(c, supabase)
  const abstractsMissing = !hasAbstractInfo(c) && c.event_type !== 'course' && !c.is_on_demand

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-bg">
      <div className="mx-auto max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
        <Breadcrumb specialty={c.specialty} title={c.conference_name} />

        {/* Mobile summary card sits above the fold, before the body content */}
        <EventSidebar conference={c} tiers={tiers} communityFields={communityFieldList} className="mb-6 lg:hidden" />

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
          <main className="min-w-0 space-y-8">
            <header className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <EventTypeBadge type={c.event_type} isFlagship={c.is_flagship} isOnDemand={c.is_on_demand} />
                {c.event_format && <FormatBadge format={c.event_format} />}
                {society && <SocietyChip name={society} />}
              </div>
              <h1 className="type-h1 text-fg-strong">{c.conference_name}</h1>
            </header>

            {c.description && (
              <section className="space-y-2">
                <h2 className="type-h3 text-fg-strong">About this event</h2>
                <p className="type-body whitespace-pre-line text-fg-muted">{c.description}</p>
              </section>
            )}

            {c.event_type === 'course' && sessions.length > 0 ? (
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="type-h3 text-fg-strong">Programme &amp; sessions</h2>
                  <span className="type-caption text-fg-subtle">
                    {sessions.filter((s) => s.availability_status !== 'sold_out').length} of {sessions.length} available
                  </span>
                </div>
                <SessionsTable
                  sessions={sessions}
                  pricingTiers={tiers}
                  parentBookingUrl={c.booking_url ?? c.organiser_url}
                />
              </section>
            ) : (
              <section className="space-y-3">
                <h2 className="type-h3 text-fg-strong">Fees</h2>
                <PricingTable tiers={tiers} organiserUrl={c.organiser_url ?? c.booking_url} conference={c} />
              </section>
            )}

            {hasAbstractInfo(c) ? (
              <AbstractsBlock conference={c} communityFields={communityFieldList} />
            ) : (
              abstractsMissing && (
                <div className="flex flex-wrap items-center justify-between gap-x-4 rounded-lg border border-dashed border-border px-4 py-1.5">
                  <p className="type-small text-fg-muted">No abstract submission details listed.</p>
                  <AddInfoTrigger conference={c} tiers={tiers} section="abstracts" variant="link">
                    Know the abstract deadline? Add it
                  </AddInfoTrigger>
                </div>
              )
            )}

            <OrganiserBlock conference={c} society={society} />

            <CommunityNotes facts={facts} hasDescription={!!c.description} />

            <ReminderPanel conference={c} sessions={sessions} />

            <RelatedEvents events={related} />
          </main>

          <EventSidebar
            conference={c}
            tiers={tiers}
            communityFields={communityFieldList}
            className="hidden self-start lg:sticky lg:top-6 lg:block"
          />
        </div>

        <div className="mt-8 border-t border-border-subtle pt-4">
          <Link href="/conferences" className="type-small text-fg-muted hover:text-brand-text">
            ← Back to directory
          </Link>
        </div>
      </div>

      <EventJsonLd conference={c} tiers={tiers} />
    </div>
  )
}
