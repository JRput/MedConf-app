// src/components/conferences/SessionsTable.tsx
'use client'

import type { CourseSession, PricingTier } from '@/lib/types'
import { Calendar, Building2, Globe, AlertCircle, Check, ExternalLink } from 'lucide-react'
import { upcomingSessions } from '@/lib/conference-helpers'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

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
      <div className="rounded-lg border border-border bg-surface-muted p-5 type-small text-fg-subtle">
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
            className={cn(
              'flex items-start gap-4 rounded-lg border border-border bg-surface px-4 py-3',
              isSold && 'opacity-60'
            )}
          >
            <div className="grid min-w-0 flex-1 grid-cols-1 items-center gap-3 sm:grid-cols-4">
              <div className="flex items-center gap-2 type-small">
                <Calendar className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                <div>
                  <p className="font-medium leading-tight text-fg-strong">
                    {formatDate(s.start_date)}
                  </p>
                  {s.end_date && s.end_date !== s.start_date && (
                    <p className="type-caption text-fg-subtle">to {formatDate(s.end_date)}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 type-small sm:col-span-2">
                {s.city ? (
                  <Building2 className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                ) : (
                  <Globe className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                )}
                <div className="min-w-0">
                  <p className="truncate text-fg">
                    {s.city ?? 'Online'}
                  </p>
                  {s.venue_name && (
                    <p className="type-caption truncate text-fg-subtle">{s.venue_name}</p>
                  )}
                </div>
              </div>

              <div className="type-small">
                <p className="type-numeric font-medium text-fg-strong">
                  {price !== null ? `£${price}` : 'Price TBC'}
                </p>
                {s.spots_left !== null && s.spots_left !== undefined && (
                  <p className="type-caption text-warn-text">{s.spots_left} spots left</p>
                )}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {isSold ? (
                <Badge variant="danger">
                  <AlertCircle className="size-3" aria-hidden />
                  Sold out
                </Badge>
              ) : isLimited ? (
                <Badge variant="warning">
                  <AlertCircle className="size-3" aria-hidden />
                  Limited
                </Badge>
              ) : (
                <Badge variant="success">
                  <Check className="size-3" aria-hidden />
                  Available
                </Badge>
              )}

              {!isSold && href && (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 rounded-sm border border-border px-2.5 py-1 type-caption font-medium text-fg transition-colors duration-150 hover:border-border-strong hover:bg-surface-hover"
                >
                  Book
                  <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
