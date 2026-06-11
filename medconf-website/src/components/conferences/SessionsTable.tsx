// src/components/conferences/SessionsTable.tsx
'use client'

import type { CourseSession, PricingTier } from '@/lib/types'
import { Calendar, MapPin, Building2, Globe, AlertCircle, Check, ExternalLink } from 'lucide-react'
import { upcomingSessions } from '@/lib/conference-helpers'

interface Props {
  sessions: CourseSession[]
  pricingTiers: PricingTier[]   // all tiers for the course; we map by session_id
  parentBookingUrl: string | null
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function priceForSession(tiers: PricingTier[], sessionId: string): number | null {
  const scoped = tiers.find(t => t.session_id === sessionId)
  if (scoped) return scoped.price_gbp
  // Fall back to a flat (session_id = null) tier if the course uses flat pricing
  const flat = tiers.find(t => !t.session_id)
  return flat ? flat.price_gbp : null
}

export function SessionsTable({ sessions, pricingTiers, parentBookingUrl }: Props) {
  const upcoming = upcomingSessions(sessions)

  if (upcoming.length === 0) {
    return (
      <div className="glass-card rounded-xl p-6 text-center text-sm text-slate-400">
        No scheduled dates yet. This course may be on-demand or have run-dates
        published soon — we&apos;ll surface them automatically when they appear.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {upcoming.map(s => {
        const isSold = s.availability_status === 'sold_out'
        const isLimited = s.availability_status === 'limited'
        const price = priceForSession(pricingTiers, s.id)
        const href = s.booking_url ?? parentBookingUrl

        return (
          <div
            key={s.id}
            className={`glass-card rounded-xl px-4 py-3 flex items-start gap-4 ${
              isSold ? 'opacity-60' : ''
            }`}
          >
            <div className="flex-1 min-w-0 grid grid-cols-1 sm:grid-cols-4 gap-3 items-center">
              <div className="flex items-center gap-2 text-sm">
                <Calendar className="w-4 h-4 text-slate-500" />
                <div>
                  <p className="text-white font-medium leading-tight">
                    {formatDate(s.start_date)}
                  </p>
                  {s.end_date && s.end_date !== s.start_date && (
                    <p className="text-xs text-slate-500">to {formatDate(s.end_date)}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 text-sm sm:col-span-2">
                {s.city ? (
                  <Building2 className="w-4 h-4 text-slate-500" />
                ) : (
                  <Globe className="w-4 h-4 text-slate-500" />
                )}
                <div className="min-w-0">
                  <p className="text-white truncate">
                    {s.city ?? 'Online'}
                  </p>
                  {s.venue_name && (
                    <p className="text-xs text-slate-500 truncate">{s.venue_name}</p>
                  )}
                </div>
              </div>

              <div className="text-sm">
                <p className="text-white font-medium">
                  {price !== null ? `£${price}` : 'Price TBC'}
                </p>
                {s.spots_left !== null && s.spots_left !== undefined && (
                  <p className="text-xs text-amber-400">{s.spots_left} spots left</p>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              {isSold ? (
                <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded bg-rose-500/15 text-rose-300 border border-rose-500/30">
                  <AlertCircle className="w-3 h-3" />
                  Sold out
                </span>
              ) : isLimited ? (
                <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
                  <AlertCircle className="w-3 h-3" />
                  Limited
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  <Check className="w-3 h-3" />
                  Available
                </span>
              )}

              {!isSold && href && (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-medium text-slate-200 hover:text-white border border-slate-700 hover:border-cyan-500/50 rounded px-2.5 py-1 flex items-center gap-1 transition-colors"
                >
                  Book
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
