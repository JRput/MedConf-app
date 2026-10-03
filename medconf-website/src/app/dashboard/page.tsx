// src/app/dashboard/page.tsx
'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import { useSavedConferences } from '@/hooks/useSavedConferences'
import { directoryEventFromRow, type DirectoryEvent, type DirectoryEventRow } from '@/lib/directory'
import { expandSpecialtyFilter } from '@/lib/directory-query'
import { SPECIALTY_PARENTS, canonicalSpecialty } from '@/lib/taxonomy/specialties'
import { AccountContainer, AccountPageHeader, AccountSection, AccountEmptyState } from '@/components/account/AccountPageHeader'
import { EventRowList } from '@/components/account/EventRowList'
import { Button } from '@/components/ui/button'
import { CalendarLinkCard } from '@/components/calendar/CalendarLinkCard'

const DAYS_30 = 30 * 86_400_000
const DAYS_7 = 7 * 86_400_000

/** Legacy profiles may still hold a raw specialty string from the old fixed
 *  onboarding list (e.g. "Cardiology") rather than a taxonomy slug — map
 *  either shape to a parent slug so queryDirectory-style filtering works
 *  the same regardless of when the user signed up. */
function toSpecialtySlug(raw: string | null): string | null {
  if (!raw) return null
  if (SPECIALTY_PARENTS.some((p) => p.slug === raw)) return raw
  return canonicalSpecialty(raw).parent
}

export default function DashboardPage() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const { events: saved, loading: savedLoading, toggleSave, savedIds } = useSavedConferences()

  const [fullName, setFullName] = useState<string | null>(null)
  const [specialtySlug, setSpecialtySlug] = useState<string | null>(null)
  const [profileLoaded, setProfileLoaded] = useState(false)
  const [deadlines, setDeadlines] = useState<DirectoryEvent[]>([])
  const [newInSpecialty, setNewInSpecialty] = useState<DirectoryEvent[]>([])
  const [feedLoading, setFeedLoading] = useState(true)

  useEffect(() => {
    if (!user) return

    supabase
      .from('user_profiles')
      .select('full_name, specialty')
      .eq('id', user.id)
      .maybeSingle()
      .then(({ data }) => {
        setFullName(data?.full_name ?? null)
        setSpecialtySlug(toSpecialtySlug(data?.specialty ?? null))
        setProfileLoaded(true)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  useEffect(() => {
    if (!profileLoaded) return
    if (!specialtySlug) {
      setDeadlines([])
      setNewInSpecialty([])
      setFeedLoading(false)
      return
    }

    const rawSpecialty = expandSpecialtyFilter([specialtySlug])
    const today = new Date().toISOString().slice(0, 10)
    const in30 = new Date(Date.now() + DAYS_30).toISOString().slice(0, 10)
    const sevenDaysAgo = new Date(Date.now() - DAYS_7).toISOString()

    setFeedLoading(true)
    Promise.all([
      supabase
        .from('directory_events')
        .select('*')
        .in('specialty', rawSpecialty)
        .not('abstract_deadline', 'is', null)
        .gte('abstract_deadline', today)
        .lte('abstract_deadline', in30)
        .order('abstract_deadline', { ascending: true })
        .limit(5),
      supabase
        .from('directory_events')
        .select('*')
        .in('specialty', rawSpecialty)
        .gte('created_at', sevenDaysAgo)
        .order('created_at', { ascending: false })
        .limit(5),
    ]).then(([deadlineResp, newResp]) => {
      setDeadlines(((deadlineResp.data ?? []) as DirectoryEventRow[]).map(directoryEventFromRow))
      setNewInSpecialty(((newResp.data ?? []) as DirectoryEventRow[]).map(directoryEventFromRow))
      setFeedLoading(false)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileLoaded, specialtySlug])

  const next30Days = useMemo(() => {
    const cutoff = new Date(Date.now() + DAYS_30).toISOString().slice(0, 10)
    const today = new Date().toISOString().slice(0, 10)
    return saved
      .filter((e) => {
        const relevantDate = e.endDate ?? e.startDate
        if (!e.startDate) return false // "Date TBC" saves don't belong on a dated timeline
        return e.startDate <= cutoff && (!relevantDate || relevantDate >= today)
      })
      .sort((a, b) => (a.startDate ?? '').localeCompare(b.startDate ?? ''))
  }, [saved])

  const specialtyLabel = specialtySlug ? SPECIALTY_PARENTS.find((p) => p.slug === specialtySlug)?.label : null
  const firstName = fullName?.split(' ')[0] || null

  return (
    <AccountContainer className="max-w-[920px]">
      <AccountPageHeader
        title={firstName ? `Welcome back, ${firstName}` : 'Your dashboard'}
        subtitle={
          specialtyLabel
            ? `Tracking ${specialtyLabel.toLowerCase()} and your saved events.`
            : 'Save events from the directory to start tracking them here.'
        }
      />

      <div className="space-y-10">
        <AccountSection
          title="Your next 30 days"
          action={
            <Link href="/saved" className="type-small font-medium text-brand-text hover:underline">
              View all saved
            </Link>
          }
        >
          <EventRowList
            events={next30Days}
            savedIds={savedIds}
            onToggleSave={(id) => toggleSave(id)}
            loading={savedLoading}
            emptyState={
              <AccountEmptyState
                title="Nothing saved yet"
                description="Save events from the directory to see them here."
                action={
                  <Button variant="outline" size="sm" asChild>
                    <Link href="/conferences">Browse the directory</Link>
                  </Button>
                }
              />
            }
          />
        </AccountSection>

        {specialtySlug && (
          <AccountSection title={`Deadlines in ${specialtyLabel}`}>
            <EventRowList
              events={deadlines}
              savedIds={savedIds}
              onToggleSave={(id) => toggleSave(id)}
              loading={feedLoading}
              emptyState={
                <AccountEmptyState title="No deadlines in the next 30 days" description="We'll surface them here as they approach." />
              }
            />
          </AccountSection>
        )}

        {specialtySlug && (
          <AccountSection title={`New in ${specialtyLabel} this week`}>
            <EventRowList
              events={newInSpecialty}
              savedIds={savedIds}
              onToggleSave={(id) => toggleSave(id)}
              loading={feedLoading}
              emptyState={<AccountEmptyState title="Nothing new this week" description="Check back soon, or browse the full directory." />}
            />
          </AccountSection>
        )}

        <CalendarLinkCard events={saved} />
      </div>
    </AccountContainer>
  )
}
