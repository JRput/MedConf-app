// src/components/conferences/ConferenceCard.tsx
import Link from 'next/link'
import { CPDBadge } from '@/components/conferences/CPDBadge'
import { SaveButton } from '@/components/ui/SaveButton'
import type { Conference, PricingTier, CourseSession } from '@/lib/types'
import { isAbstractEffectivelyOpen, courseSessionSummary } from '@/lib/conference-helpers'
import { Calendar, Clock, MapPin, PoundSterling, ArrowRight, ExternalLink, FileText, Globe, Building2, Layers } from 'lucide-react'

interface ConferenceCardProps {
  conference: Conference
  tiers: PricingTier[]
  sourceName?: string | null
  sessions?: CourseSession[]
  /** When true, render the "NEW" badge if the conference was added in the
   * last 7 days. Used by the directory when sort=recently_added so users
   * arriving from a "new in your specialty" notification can spot the
   * newcomers at a glance. */
  showNewBadge?: boolean
}

const FORMAT_LABEL: Record<string, { label: string; Icon: typeof Globe }> = {
  online: { label: 'Online', Icon: Globe },
  in_person: { label: 'In-person', Icon: Building2 },
  hybrid: { label: 'Hybrid', Icon: Globe },
}

export function ConferenceCard({ conference: c, tiers, sourceName, sessions, showNewBadge = false }: ConferenceCardProps) {
  const isCourse = c.event_type === 'course'
  const courseSummary = isCourse ? courseSessionSummary(sessions) : null

  const isNew = showNewBadge && c.created_at
    && (Date.now() - new Date(c.created_at).getTime()) < 7 * 86_400_000

  const minPrice = tiers.length ? Math.min(...tiers.map(t => t.price_gbp)) : null
  const maxPrice = tiers.length ? Math.max(...tiers.map(t => t.price_gbp)) : null
  const priceLabel = minPrice === 0
    ? (maxPrice === 0 ? 'Free' : `Free – £${maxPrice}`)
    : isCourse && minPrice !== null
      ? `From £${minPrice}`
      : minPrice !== null
        ? (minPrice === maxPrice ? `£${minPrice}` : `£${minPrice} – £${maxPrice}`)
        : 'Price TBC'

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null
    return new Date(dateStr).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    })
  }

  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return null
    return timeStr.slice(0, 5) // HH:MM:SS → HH:MM
  }

  // For courses, the headline date is the next available session's date.
  // For conferences, the conference's own date range.
  let dateDisplay: string
  if (isCourse) {
    const next = courseSummary?.next
    if (next) {
      const ns = formatDate(next.start_date)
      const ne = formatDate(next.end_date)
      dateDisplay = ne && next.end_date !== next.start_date && ne !== ns
        ? `Next: ${ns} – ${ne}`
        : `Next: ${ns}`
    } else if (courseSummary?.total === 0) {
      dateDisplay = 'No scheduled dates'
    } else {
      dateDisplay = 'Date TBC'
    }
  } else {
    const startFormatted = formatDate(c.start_date)
    const endFormatted = formatDate(c.end_date)
    dateDisplay = startFormatted
      ? (endFormatted && c.end_date !== c.start_date
          ? `${startFormatted} – ${endFormatted}`
          : startFormatted)
      : 'Date TBC'
  }

  const startTimeDisplay = formatTime(c.start_time)
  const formatBadge = c.event_format ? FORMAT_LABEL[c.event_format] : null
  const externalUrl = c.booking_url ?? c.organiser_url

  // Days until the abstract deadline, if any. Returned for the urgency
  // badge — only shown when the deadline is between today and 14 days
  // away. After that we drop into the normal abstract badge below.
  const daysUntilDeadline: number | null = (() => {
    if (!c.abstract_deadline) return null
    const diff = Math.ceil(
      (new Date(c.abstract_deadline).getTime() - Date.now()) / 86_400_000
    )
    return diff
  })()
  const showDeadlineBadge = daysUntilDeadline !== null && daysUntilDeadline >= 0 && daysUntilDeadline <= 14

  return (
    <div className={`group glass-card rounded-xl p-5 flex flex-col gap-4 transition-all duration-300 relative ${
      c.is_sold_out
        ? 'opacity-70 hover:border-rose-500/30'
        : 'hover:border-cyan-500/30'
    }`}>
      {/* Sold-out overlay badge */}
      {c.is_sold_out && (
        <span className="absolute top-3 right-3 z-10 inline-flex items-center gap-1 bg-rose-500/15 border border-rose-500/40 text-rose-300 text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-md">
          Sold out
        </span>
      )}

      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex flex-col gap-1.5 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider truncate">
              {c.specialty || 'General'}
            </span>
            {isCourse && (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 border border-violet-500/30 flex-shrink-0">
                <Layers className="w-3 h-3" />
                Course
              </span>
            )}
            {isNew && (
              <span className="inline-flex items-center text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex-shrink-0">
                New
              </span>
            )}
          </div>
          {sourceName && (
            <span className="inline-flex items-center self-start text-[10px] font-medium uppercase tracking-wider text-slate-400 bg-slate-800/60 border border-slate-700 rounded px-1.5 py-0.5">
              {sourceName}
            </span>
          )}
        </div>
        {!c.is_sold_out && <CPDBadge accredited={c.cpd_accredited} points={c.cpd_points} />}
      </div>

      {/* Title */}
      <Link href={`/conferences/${c.id}`} className="block">
        <h3 className="font-bold text-white text-lg leading-tight group-hover:text-cyan-400 transition-colors line-clamp-2">
          {c.conference_name}
        </h3>
      </Link>

      {/* Details */}
      <div className="space-y-2.5 text-sm text-slate-400">
        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-slate-500" />
          <span>{dateDisplay}</span>
        </div>

        {startTimeDisplay && (
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-500" />
            <span>{startTimeDisplay}</span>
          </div>
        )}

        {/* Location row — always renders. For online events we show "Online"
            even when no venue is published; otherwise venue+city, or a
            "Location TBC" placeholder when neither is known yet. */}
        <div className="flex items-center gap-2">
          {formatBadge ? (
            <formatBadge.Icon className="w-4 h-4 text-slate-500" />
          ) : (
            <MapPin className="w-4 h-4 text-slate-500" />
          )}
          {c.event_format === 'online' ? (
            <span className="text-cyan-300 font-medium">Online</span>
          ) : c.event_format === 'hybrid' && (c.venue_name || c.city) ? (
            <span>
              <span className="text-cyan-300 font-medium">Hybrid</span>
              <span className="text-slate-400">
                {' — '}{[c.venue_name, c.city].filter(Boolean).join(', ')}
              </span>
            </span>
          ) : isCourse && courseSummary && courseSummary.total > 0 ? (
            // Course mode: prefer next-session city, fall back to "Multiple
            // locations" when sessions span more than one venue.
            (() => {
              const cities = new Set(
                courseSummary.upcoming
                  .map(s => s.city)
                  .filter((c): c is string => !!c)
              )
              const nextCity = courseSummary.next?.city
              if (cities.size === 0) return <span className="text-slate-500 italic">Location TBC</span>
              if (cities.size === 1 && nextCity) return <span>{nextCity}</span>
              return (
                <span>
                  {nextCity ?? 'Multiple locations'}
                  <span className="text-slate-500">
                    {' '}· {cities.size} location{cities.size === 1 ? '' : 's'}
                  </span>
                </span>
              )
            })()
          ) : (c.venue_name || c.city) ? (
            <span>{[c.venue_name, c.city].filter(Boolean).join(', ')}</span>
          ) : (
            <span className="text-slate-500 italic">Location TBC</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <PoundSterling className="w-4 h-4 text-slate-500" />
          <span className="font-medium text-white">{priceLabel}</span>
        </div>

        {/* Status line — semantics depend on event_type. Course cards
            replace the abstracts indicator with a session-count badge. */}
        {isCourse && courseSummary ? (
          courseSummary.total === 0 ? (
            <div className="flex items-center gap-2 text-slate-500">
              <Layers className="w-4 h-4" />
              <span className="text-xs font-medium">On-demand · no scheduled dates</span>
            </div>
          ) : courseSummary.allSoldOut ? (
            <div className="flex items-center gap-2 text-rose-400">
              <Layers className="w-4 h-4" />
              <span className="text-xs font-medium">
                All {courseSummary.total} upcoming sold out
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-cyan-400">
              <Layers className="w-4 h-4" />
              <span className="text-xs font-medium">
                {courseSummary.available} of {courseSummary.total} upcoming{' '}
                session{courseSummary.total === 1 ? '' : 's'} available
              </span>
            </div>
          )
        ) : showDeadlineBadge ? (
          <div className="flex items-center gap-2 text-amber-400">
            <FileText className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wider">
              {daysUntilDeadline === 0 ? 'Deadline today' :
               daysUntilDeadline === 1 ? '1 day left' :
               `${daysUntilDeadline} days left`}
            </span>
          </div>
        ) : isAbstractEffectivelyOpen(c) ? (
          <div className="flex items-center gap-2 text-amber-400">
            <FileText className="w-4 h-4" />
            <span className="text-xs font-medium">Abstracts Open</span>
          </div>
        ) : c.abstract_deadline ? (
          <div className="flex items-center gap-2 text-slate-500">
            <FileText className="w-4 h-4" />
            <span className="text-xs font-medium">Abstracts Closed</span>
          </div>
        ) : null}
      </div>

      {/* Actions */}
      <div className="mt-auto pt-3 flex justify-between items-center gap-2 border-t border-slate-800">
        <Link
          href={`/conferences/${c.id}`}
          className="text-sm text-cyan-400 font-medium hover:text-cyan-300 flex items-center gap-1 transition-colors"
        >
          View details
          <ArrowRight className="w-4 h-4" />
        </Link>
        <div className="flex items-center gap-2">
          {externalUrl && (
            <a
              href={externalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-slate-300 hover:text-white border border-slate-700 hover:border-cyan-500/50 rounded-md px-2.5 py-1 flex items-center gap-1 transition-colors"
              aria-label={`Open ${c.conference_name} on the organiser site in a new tab`}
            >
              View course
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
          <SaveButton conferenceId={c.id} size="sm" />
        </div>
      </div>
    </div>
  )
}


