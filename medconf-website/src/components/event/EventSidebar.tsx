'use client'

import { useState } from 'react'
import { Calendar, MapPin, Building2, Globe, MonitorSmartphone, ExternalLink, Download, Share2, Check, Clock, Bookmark } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CpdLabel } from '@/components/domain/CpdLabel'
import { PriceLabel } from '@/components/domain/PriceLabel'
import type { Conference, PricingTier } from '@/lib/types'
import { formatDateRange } from '@/lib/format'
import { downloadIcs } from '@/lib/ics'
import { useAuth } from '@/hooks/useAuth'
import { useSaved } from '@/hooks/useSaved'
import { cn } from '@/lib/utils'

/**
 * The sticky right panel on desktop / summary card on mobile — everything a
 * reader needs to decide "is this worth registering for" without scrolling
 * into the body copy. Client component: Save/calendar/share all need the
 * browser, and Save additionally needs auth state.
 */
export function EventSidebar({
  conference,
  tiers,
  className,
}: {
  conference: Conference
  tiers: PricingTier[]
  className?: string
}) {
  const c = conference
  const { user } = useAuth()
  const { isSaved, toggleSave } = useSaved()
  const saved = isSaved(c.id)

  const prices = tiers.map((t) => Number(t.price_gbp)).filter((n) => Number.isFinite(n))
  const priceMin = prices.length ? Math.min(...prices) : null
  const priceMax = prices.length ? Math.max(...prices) : null
  const currency = tiers.find((t) => t.currency)?.currency ?? 'GBP'

  const mapHref =
    c.event_format !== 'online' && (c.venue_name || c.city)
      ? `https://www.google.com/maps/search/${encodeURIComponent([c.venue_name, c.city, c.region].filter(Boolean).join(', '))}`
      : null

  return (
    <aside
      className={cn(
        'space-y-5 rounded-lg border border-border bg-surface p-5 shadow-xs',
        className
      )}
    >
      {/* Date */}
      <div className="flex items-start gap-3">
        <Calendar className="mt-0.5 size-4 shrink-0 text-fg-subtle" strokeWidth={1.75} aria-hidden />
        <div>
          <p className="type-body font-medium text-fg-strong">
            {formatDateRange(c.start_date, c.end_date)}
          </p>
          {c.start_time && (
            <p className="type-small text-fg-muted">
              <Clock className="mr-1 inline size-3.5 -translate-y-px" strokeWidth={1.75} aria-hidden />
              {c.start_time.slice(0, 5)}
            </p>
          )}
        </div>
      </div>

      {/* Format + location */}
      <div className="flex items-start gap-3 border-t border-border-subtle pt-4">
        <FormatIcon format={c.event_format} />
        <div className="min-w-0">
          {c.event_format === 'online' ? (
            <p className="type-body font-medium text-fg-strong">Online</p>
          ) : (c.venue_name || c.city) ? (
            <>
              <p className="type-body font-medium text-fg-strong">
                {[c.venue_name, c.city].filter(Boolean).join(', ')}
              </p>
              {c.region && <p className="type-small text-fg-muted">{c.region}</p>}
              {mapHref && (
                <a
                  href={mapHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="type-small mt-1 inline-flex items-center gap-1 text-brand-text hover:underline"
                >
                  View on map <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </>
          ) : (
            <p className="type-body text-fg-subtle italic">Location TBC</p>
          )}
        </div>
      </div>

      {/* CPD + price */}
      {(c.cpd_accredited || priceMin !== null) && (
        <div className="flex items-center justify-between gap-3 border-t border-border-subtle pt-4">
          <CpdLabel accredited={c.cpd_accredited} points={c.cpd_points} size="md" />
          <PriceLabel min={priceMin} max={priceMax} currency={currency} href={c.organiser_url ?? c.booking_url} size="md" />
        </div>
      )}

      {/* Primary actions */}
      <div className="space-y-2 border-t border-border-subtle pt-4">
        {c.organiser_url ? (
          <Button asChild className="w-full">
            <a href={c.organiser_url} target="_blank" rel="noopener noreferrer">
              Book on organiser&apos;s site
              <ExternalLink className="size-4" aria-hidden />
            </a>
          </Button>
        ) : (
          <p className="type-small text-fg-subtle">Booking link coming soon.</p>
        )}

        <div className="grid grid-cols-2 gap-2">
          <Button
            variant="outline"
            onClick={() => {
              if (!user) {
                window.location.href = '/auth/login'
                return
              }
              toggleSave(c.id)
            }}
            aria-pressed={saved}
            className={cn(saved && 'text-brand-text')}
          >
            <Bookmark className="size-4" strokeWidth={1.75} fill={saved ? 'currentColor' : 'none'} aria-hidden />
            {saved ? 'Saved' : 'Save'}
          </Button>
          <CalendarButton conference={c} />
        </div>
        <ShareButton conference={c} />
      </div>
    </aside>
  )
}

function FormatIcon({ format }: { format: Conference['event_format'] }) {
  const Icon = format === 'online' ? Globe : format === 'hybrid' ? MonitorSmartphone : format === 'in_person' ? Building2 : MapPin
  return <Icon className="mt-0.5 size-4 shrink-0 text-fg-subtle" strokeWidth={1.75} aria-hidden />
}

function CalendarButton({ conference }: { conference: Conference }) {
  if (!conference.start_date && !conference.abstract_deadline) return null
  return (
    // Labelled for what it is: a file for an EXTERNAL calendar. Inside
    // MedConf, saving an event is what puts it on /calendar — there is no
    // separate "add to calendar" step to confuse this with.
    <Button variant="outline" onClick={() => downloadIcs(conference)}>
      <Download className="size-4" aria-hidden />
      Export .ics
    </Button>
  )
}

function ShareButton({ conference }: { conference: Conference }) {
  const [copied, setCopied] = useState(false)

  const handleShare = async () => {
    const url = typeof window !== 'undefined' ? window.location.href : ''
    const title = conference.conference_name
    if (typeof navigator !== 'undefined' && navigator.share) {
      try {
        await navigator.share({ title, url })
        return
      } catch {
        // user cancelled — fall through to clipboard
      }
    }
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // most browsers allow clipboard.writeText in a user gesture; ignore otherwise
    }
  }

  return (
    <Button variant="ghost" className="w-full" onClick={handleShare}>
      {copied ? <Check className="size-4 text-ok-text" aria-hidden /> : <Share2 className="size-4" aria-hidden />}
      {copied ? 'Link copied' : 'Share'}
    </Button>
  )
}
