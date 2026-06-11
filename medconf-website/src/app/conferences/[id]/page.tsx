// src/app/conferences/[id]/page.tsx
'use client'

import { useState, useEffect, use } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { CPDBadge } from '@/components/conferences/CPDBadge'
import { PricingTable } from '@/components/conferences/PricingTable'
import { ReminderPanel } from '@/components/conferences/ReminderPanel'
import { SaveButton } from '@/components/ui/SaveButton'
import type { Conference, PricingTier } from '@/lib/types'
import Link from 'next/link'
import { ArrowLeft, Calendar, MapPin, FileText, Clock, ExternalLink, Loader2, AlertCircle, Globe, Building2, Download, Share2, Check } from 'lucide-react'
import { downloadIcs } from '@/lib/ics'
import { isAbstractEffectivelyOpen } from '@/lib/conference-helpers'

export default function ConferenceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params)
  const [conference, setConference] = useState<Conference | null>(null)
  const [tiers, setTiers] = useState<PricingTier[]>([])
  const [loading, setLoading] = useState(true)
  const supabase = createSupabaseClient()

  useEffect(() => {
    async function fetchConference() {
      const { data: conf } = await supabase
        .from('conferences')
        .select('*')
        .eq('id', Number(resolvedParams.id))
        .single()
      
      const { data: pricing } = await supabase
        .from('pricing_tiers')
        .select('*')
        .eq('conference_id', Number(resolvedParams.id))

      if (conf) setConference(conf)
      if (pricing) setTiers(pricing)
      setLoading(false)
    }

    fetchConference()
  }, [resolvedParams.id])

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-4" />
          <p className="text-slate-400 text-sm">Loading conference details...</p>
        </div>
      </div>
    )
  }

  if (!conference) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
            <AlertCircle className="w-8 h-8 text-rose-400" />
          </div>
          <h1 className="text-xl font-bold text-white mb-2">Conference not found</h1>
          <p className="text-slate-400 mb-6">This conference may have been removed or doesn&apos;t exist.</p>
          <Link 
            href="/conferences"
            className="inline-flex items-center gap-2 text-cyan-400 hover:text-cyan-300 font-medium"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to directory
          </Link>
        </div>
      </div>
    )
  }

  const c = conference

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null
    return new Date(dateStr).toLocaleDateString('en-GB', { 
      weekday: 'long',
      day: 'numeric', 
      month: 'long', 
      year: 'numeric' 
    })
  }

  const startFormatted = formatDate(c.start_date)
  const endFormatted = c.end_date && c.end_date !== c.start_date 
    ? new Date(c.end_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })
    : null

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      {/* Background */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back link */}
        <Link 
          href="/conferences"
          className="inline-flex items-center gap-2 text-slate-400 hover:text-cyan-400 text-sm font-medium mb-6 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to directory
        </Link>

        <div className="glass-card rounded-2xl p-6 sm:p-8 space-y-8">
          {/* Header */}
          <div className="flex flex-col sm:flex-row justify-between items-start gap-4">
            <div className="flex-1">
              <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                {c.specialty || 'General'}
              </span>
              <h1 className="text-2xl sm:text-3xl font-bold text-white mt-2 font-display">
                {c.conference_name}
              </h1>
            </div>
            <div className="flex items-center gap-2">
              <ShareButton conference={c} />
              <CalendarButton conference={c} />
              <SaveButton conferenceId={c.id} />
            </div>
          </div>

          {/* CPD badge */}
          <div>
            <CPDBadge accredited={c.cpd_accredited} points={c.cpd_points} />
          </div>

          {/* Key details grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {startFormatted && (
              <div className="space-y-1">
                <p className="text-sm font-medium text-slate-400 flex items-center gap-2">
                  <Calendar className="w-4 h-4" />
                  Date
                </p>
                <p className="text-white">
                  {startFormatted}
                  {endFormatted && ` – ${endFormatted}`}
                </p>
              </div>
            )}

            {/* Location — format-aware. Always renders so users know
                whether an event is online/in-person even before a venue is
                published. */}
            <div className="space-y-1">
              <p className="text-sm font-medium text-slate-400 flex items-center gap-2">
                {c.event_format === 'online' ? (
                  <Globe className="w-4 h-4" />
                ) : c.event_format === 'in_person' ? (
                  <Building2 className="w-4 h-4" />
                ) : (
                  <MapPin className="w-4 h-4" />
                )}
                Location
              </p>
              {c.event_format === 'online' ? (
                <p className="text-cyan-300 font-medium">Online</p>
              ) : c.event_format === 'hybrid' ? (
                <p className="text-white">
                  <span className="text-cyan-300 font-medium">Hybrid</span>
                  {(c.venue_name || c.city) && (
                    <span className="text-slate-300">
                      {' — '}
                      {[c.venue_name, c.city].filter(Boolean).join(', ')}
                      {c.region && ` (${c.region})`}
                    </span>
                  )}
                </p>
              ) : (c.venue_name || c.city) ? (
                <p className="text-white">
                  {[c.venue_name, c.city].filter(Boolean).join(', ')}
                  {c.region && ` (${c.region})`}
                </p>
              ) : (
                <p className="text-slate-500 italic">Location TBC</p>
              )}
            </div>

            <div className="space-y-1">
              <p className="text-sm font-medium text-slate-400 flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Abstract Submissions
              </p>
              <p className={isAbstractEffectivelyOpen(c) ? 'text-emerald-400 font-semibold' : 'text-slate-300'}>
                {isAbstractEffectivelyOpen(c) ? 'Open' : 'Closed'}
                {isAbstractEffectivelyOpen(c) && c.abstract_deadline && (
                  <span className="text-amber-400 ml-2">
                    – deadline {new Date(c.abstract_deadline).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })}
                  </span>
                )}
              </p>
            </div>
          </div>

          {/* Description */}
          {c.description && (
            <div className="space-y-3">
              <h2 className="font-bold text-white text-lg">About this conference</h2>
              <p className="text-slate-300 leading-relaxed">{c.description}</p>
            </div>
          )}

          {/* Reminders */}
          <ReminderPanel conference={c} />

          {/* Pricing */}
          <div className="space-y-4">
            <h2 className="font-bold text-white text-lg">Pricing</h2>
            <PricingTable tiers={tiers} />
          </div>

          {/* Book CTA */}
          <div className="bg-gradient-to-r from-cyan-500/10 to-teal-500/10 border border-cyan-500/20 rounded-xl p-6 text-center">
            <p className="text-slate-300 mb-4">
              Ready to attend? Book directly on the organiser&apos;s website.
            </p>
            {c.organiser_url ? (
              <a 
                href={c.organiser_url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-8 py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25"
              >
                Book on Official Site
                <ExternalLink className="w-4 h-4" />
              </a>
            ) : (
              <p className="text-slate-400 text-sm">Booking link coming soon.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function CalendarButton({ conference }: { conference: Conference }) {
  // Only useful when we have a date to put on the calendar
  if (!conference.start_date && !conference.abstract_deadline) return null
  return (
    <button
      onClick={() => downloadIcs(conference)}
      aria-label="Add to calendar"
      className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white border border-slate-700 hover:border-cyan-500/50 rounded-md px-2.5 py-1.5 transition-colors"
    >
      <Download className="w-3.5 h-3.5" />
      <span className="hidden sm:inline">Add to calendar</span>
    </button>
  )
}

function ShareButton({ conference }: { conference: Conference }) {
  const [copied, setCopied] = useState(false)

  const handleShare = async () => {
    const url = typeof window !== 'undefined' ? window.location.href : ''
    const title = conference.conference_name
    // Try the native share sheet first (mobile / supported browsers)
    if (typeof navigator !== 'undefined' && navigator.share) {
      try {
        await navigator.share({ title, url })
        return
      } catch {
        // user cancelled, fall through to clipboard
      }
    }
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore — most browsers allow clipboard.writeText in user gesture
    }
  }

  return (
    <button
      onClick={handleShare}
      aria-label="Share conference"
      className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white border border-slate-700 hover:border-cyan-500/50 rounded-md px-2.5 py-1.5 transition-colors"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Share2 className="w-3.5 h-3.5" />}
      <span className="hidden sm:inline">{copied ? 'Copied' : 'Share'}</span>
    </button>
  )
}


