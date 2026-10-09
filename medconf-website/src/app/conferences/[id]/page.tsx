// src/app/conferences/[id]/page.tsx
// Server-rendered — public and indexable, so metadata/JSON-LD need real
// HTML on first response rather than a client-side fetch. Interactive bits
// (save, calendar, share, reminders) live in client components underneath.

import { notFound } from 'next/navigation'
import Link from 'next/link'
import type { Metadata } from 'next'
import { createSupabaseServerClient } from '@/lib/supabase-server'
import { resolveDirectory, wantsFixture } from '@/lib/directory-source'
import { expandSpecialtyFilter, type DirectoryFilters } from '@/lib/directory-query'
import { canonicalSpecialty } from '@/lib/taxonomy/specialties'
import type { Conference, PricingTier, CourseSession, SourceSummary } from '@/lib/types'
import { hasAbstractInfo } from '@/lib/conference-helpers'
import { formatDateRange } from '@/lib/format'

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

async function fetchConferenceData(id: number) {
  const supabase = createSupabaseServerClient()

  const [confResp, pricingResp, sessionsResp] = await Promise.all([
    supabase.from('conferences').select('*').eq('id', id).eq('archived', false).single(),
    supabase.from('pricing_tiers').select('*').eq('conference_id', id),
    supabase.from('course_sessions').select('*').eq('course_id', id).order('start_date', { ascending: true }),
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

  return { conference, tiers, sessions, society }
}

async function fetchRelatedEvents(conference: Conference) {
  if (!conference.start_date) return []

  const supabase = createSupabaseServerClient()
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

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params
  const data = await fetchConferenceData(Number(id))
  if (!data) return { title: 'Event not found — MedConf' }

  const { conference: c } = data
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

export default async function ConferenceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const data = await fetchConferenceData(Number(id))
  if (!data) notFound()

  const { conference: c, tiers, sessions, society } = data
  const related = await fetchRelatedEvents(c)

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-bg">
      <div className="mx-auto max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
        <Breadcrumb specialty={c.specialty} title={c.conference_name} />

        {/* Mobile summary card sits above the fold, before the body content */}
        <EventSidebar conference={c} tiers={tiers} className="mb-6 lg:hidden" />

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
                <PricingTable tiers={tiers} organiserUrl={c.organiser_url ?? c.booking_url} />
              </section>
            )}

            {hasAbstractInfo(c) && <AbstractsBlock conference={c} />}

            <OrganiserBlock conference={c} society={society} />

            <ReminderPanel conference={c} sessions={sessions} />

            <RelatedEvents events={related} />
          </main>

          <EventSidebar conference={c} tiers={tiers} className="hidden self-start lg:sticky lg:top-6 lg:block" />
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
