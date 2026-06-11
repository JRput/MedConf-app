// src/app/dashboard/page.tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import type { Conference } from '@/lib/types'
import {
  Bookmark, Calendar, Bell, FileText, Sparkles, Clock,
  ArrowRight, Loader2, MapPin, Building2,
} from 'lucide-react'

interface DashboardData {
  fullName: string | null
  specialty: string | null
  totalSaved: number
  upcomingSaved: Conference[]
  closingDeadlines: Conference[]
  newInSpecialty: Conference[]
}

export default function DashboardPage() {
  const { user } = useAuth()
  const supabase = createSupabaseClient()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!user) return

    const load = async () => {
      const today = new Date().toISOString().slice(0, 10)
      const in14 = new Date(Date.now() + 14 * 86400_000).toISOString().slice(0, 10)
      const oneWeekAgo = new Date(Date.now() - 7 * 86400_000).toISOString()

      const [profileResp, savedIdsResp] = await Promise.all([
        supabase
          .from('user_profiles')
          .select('full_name, specialty')
          .eq('id', user.id)
          .single(),
        supabase
          .from('saved_conferences')
          .select('conference_id')
          .eq('user_id', user.id),
      ])

      const fullName = profileResp.data?.full_name ?? null
      const specialty = profileResp.data?.specialty ?? null
      const savedIds = (savedIdsResp.data ?? []).map(r => r.conference_id)
      const totalSaved = savedIds.length

      let upcomingSaved: Conference[] = []
      if (savedIds.length > 0) {
        const { data: rows } = await supabase
          .from('conferences')
          .select('*')
          .in('id', savedIds)
          .eq('archived', false)
          .gte('start_date', today)
          .order('start_date', { ascending: true })
          .limit(3)
        upcomingSaved = rows ?? []
      }

      const { data: closingRows } = await supabase
        .from('conferences')
        .select('*')
        .eq('archived', false)
        .not('abstract_deadline', 'is', null)
        .gte('abstract_deadline', today)
        .lte('abstract_deadline', in14)
        .order('abstract_deadline', { ascending: true })
        .limit(3)

      let newInSpecialty: Conference[] = []
      if (specialty) {
        const { data: rows } = await supabase
          .from('conferences')
          .select('*')
          .eq('archived', false)
          .ilike('specialty', specialty)
          .gte('created_at', oneWeekAgo)
          .order('created_at', { ascending: false })
          .limit(3)
        newInSpecialty = rows ?? []
      }

      setData({
        fullName,
        specialty,
        totalSaved,
        upcomingSaved,
        closingDeadlines: closingRows ?? [],
        newInSpecialty,
      })
      setLoading(false)
    }

    load()
  }, [user, supabase])

  if (loading || !data) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
      </div>
    )
  }

  const firstName = data.fullName?.split(' ')[0] || 'there'
  const nextDeadline = data.closingDeadlines[0]
  const daysUntil = (dateStr: string | null) => {
    if (!dateStr) return null
    const diff = Math.ceil(
      (new Date(dateStr).getTime() - Date.now()) / 86400_000
    )
    return diff
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold text-white font-display">
            Welcome back, {firstName}
          </h1>
          {nextDeadline ? (
            <p className="text-slate-400 mt-2">
              Your next abstract deadline:{' '}
              <Link
                href={`/conferences/${nextDeadline.id}`}
                className="text-cyan-400 hover:text-cyan-300"
              >
                {nextDeadline.conference_name}
              </Link>
              {' '}in {daysUntil(nextDeadline.abstract_deadline)} days
            </p>
          ) : (
            <p className="text-slate-400 mt-2">
              {data.specialty
                ? `Showing conferences tailored to your interest in ${data.specialty}.`
                : 'Browse the directory to find conferences and save the ones that interest you.'}
            </p>
          )}
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard
            icon={Bookmark}
            label="Saved conferences"
            value={data.totalSaved.toString()}
            href="/saved"
            tint="cyan"
          />
          <StatCard
            icon={Clock}
            label="Deadlines in next 14 days"
            value={data.closingDeadlines.length.toString()}
            href="/conferences"
            tint="amber"
          />
          <StatCard
            icon={Sparkles}
            label={data.specialty ? `New in ${data.specialty}` : 'New this week'}
            value={data.newInSpecialty.length.toString()}
            href="/conferences"
            tint="teal"
          />
        </div>

        {/* Saved upcoming */}
        <Section
          title="Your upcoming saved conferences"
          actionLabel="View all"
          actionHref="/saved"
        >
          {data.upcomingSaved.length === 0 ? (
            <EmptyState
              icon={Bookmark}
              title="Nothing saved yet"
              description="Browse the directory and click the save button on conferences you want to track."
              ctaLabel="Browse conferences"
              ctaHref="/conferences"
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {data.upcomingSaved.map(c => <MiniConferenceCard key={c.id} c={c} />)}
            </div>
          )}
        </Section>

        {/* Closing soon */}
        <Section
          title="Abstract deadlines closing soon"
          actionLabel="See all"
          actionHref="/conferences"
        >
          {data.closingDeadlines.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No deadlines in the next 14 days"
              description="We'll surface them here as they approach."
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {data.closingDeadlines.map(c => <MiniConferenceCard key={c.id} c={c} highlightDeadline />)}
            </div>
          )}
        </Section>

        {/* What's coming */}
        <Section title="Coming to your dashboard">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <FeatureCard
              icon={Bell}
              title="In-app reminders"
              description="Set custom reminders for abstract deadlines and conference start dates. You'll see them right here in the bell icon."
              comingSoon
            />
            <FeatureCard
              icon={FileText}
              title="Submission tracker"
              description="Log every abstract you submit and track it from Submitted → Under Review → Accepted across every conference."
              comingSoon
            />
          </div>
        </Section>

      </div>
    </div>
  )
}

function StatCard({
  icon: Icon, label, value, href, tint,
}: {
  icon: typeof Bookmark
  label: string
  value: string
  href: string
  tint: 'cyan' | 'amber' | 'teal'
}) {
  const tints = {
    cyan: 'border-cyan-500/30 hover:border-cyan-500/60 text-cyan-400',
    amber: 'border-amber-500/30 hover:border-amber-500/60 text-amber-400',
    teal: 'border-teal-500/30 hover:border-teal-500/60 text-teal-400',
  }
  return (
    <Link
      href={href}
      className={`glass-card rounded-xl p-5 border transition-all ${tints[tint]}`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-400">{label}</p>
          <p className="text-3xl font-bold text-white mt-2">{value}</p>
        </div>
        <Icon className={`w-6 h-6 ${tints[tint].split(' ').pop()}`} />
      </div>
    </Link>
  )
}

function Section({
  title, actionLabel, actionHref, children,
}: {
  title: string
  actionLabel?: string
  actionHref?: string
  children: React.ReactNode
}) {
  return (
    <section>
      <div className="flex items-end justify-between mb-4">
        <h2 className="text-lg font-bold text-white">{title}</h2>
        {actionLabel && actionHref && (
          <Link href={actionHref} className="text-sm text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
            {actionLabel} <ArrowRight className="w-4 h-4" />
          </Link>
        )}
      </div>
      {children}
    </section>
  )
}

function MiniConferenceCard({ c, highlightDeadline = false }: { c: Conference; highlightDeadline?: boolean }) {
  const dateLabel = c.start_date
    ? new Date(c.start_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : 'Date TBC'
  const deadlineLabel = c.abstract_deadline
    ? new Date(c.abstract_deadline).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
    : null
  const daysLeft = c.abstract_deadline
    ? Math.ceil((new Date(c.abstract_deadline).getTime() - Date.now()) / 86400_000)
    : null

  return (
    <Link
      href={`/conferences/${c.id}`}
      className="glass-card rounded-xl p-4 block hover:border-cyan-500/30 transition-all"
    >
      {c.specialty && (
        <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
          {c.specialty}
        </span>
      )}
      <h3 className="font-bold text-white text-sm leading-tight line-clamp-2 mt-1">
        {c.conference_name}
      </h3>
      <div className="mt-3 space-y-1.5 text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <Calendar className="w-3.5 h-3.5 text-slate-500" />
          <span>{dateLabel}</span>
        </div>
        {(c.city || c.event_format) && (
          <div className="flex items-center gap-2">
            {c.event_format === 'online'
              ? <MapPin className="w-3.5 h-3.5 text-slate-500" />
              : <Building2 className="w-3.5 h-3.5 text-slate-500" />}
            <span>
              {c.event_format === 'online' ? 'Online' : (c.city || 'Location TBC')}
            </span>
          </div>
        )}
        {highlightDeadline && deadlineLabel && (
          <div className="flex items-center gap-2 text-amber-400 font-medium">
            <Clock className="w-3.5 h-3.5" />
            <span>
              Deadline {deadlineLabel}{daysLeft !== null ? ` · ${daysLeft}d left` : ''}
            </span>
          </div>
        )}
      </div>
    </Link>
  )
}

function EmptyState({
  icon: Icon, title, description, ctaLabel, ctaHref,
}: {
  icon: typeof Bookmark
  title: string
  description: string
  ctaLabel?: string
  ctaHref?: string
}) {
  return (
    <div className="glass-card rounded-xl p-8 text-center">
      <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-slate-800/50 flex items-center justify-center">
        <Icon className="w-6 h-6 text-slate-500" />
      </div>
      <h3 className="text-white font-semibold mb-1">{title}</h3>
      <p className="text-sm text-slate-400 max-w-md mx-auto">{description}</p>
      {ctaLabel && ctaHref && (
        <Link
          href={ctaHref}
          className="inline-flex items-center gap-2 mt-4 text-cyan-400 hover:text-cyan-300 text-sm font-medium"
        >
          {ctaLabel} <ArrowRight className="w-4 h-4" />
        </Link>
      )}
    </div>
  )
}

function FeatureCard({
  icon: Icon, title, description, comingSoon = false,
}: {
  icon: typeof Bookmark
  title: string
  description: string
  comingSoon?: boolean
}) {
  return (
    <div className="glass-card rounded-xl p-5 border border-slate-700/50">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-slate-800/50 border border-slate-700 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-slate-400" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-white">{title}</h3>
            {comingSoon && (
              <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                Coming soon
              </span>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1.5 leading-relaxed">{description}</p>
        </div>
      </div>
    </div>
  )
}
