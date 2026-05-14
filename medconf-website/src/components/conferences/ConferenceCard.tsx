// src/components/conferences/ConferenceCard.tsx
import Link from 'next/link'
import { CPDBadge } from '@/components/conferences/CPDBadge'
import { SaveButton } from '@/components/ui/SaveButton'
import type { Conference, PricingTier } from '@/lib/types'
import { Calendar, Clock, MapPin, PoundSterling, ArrowRight, ExternalLink, FileText, Globe, Building2 } from 'lucide-react'

interface ConferenceCardProps {
  conference: Conference
  tiers: PricingTier[]
  sourceName?: string | null
}

const FORMAT_LABEL: Record<string, { label: string; Icon: typeof Globe }> = {
  online: { label: 'Online', Icon: Globe },
  in_person: { label: 'In-person', Icon: Building2 },
  hybrid: { label: 'Hybrid', Icon: Globe },
}

export function ConferenceCard({ conference: c, tiers, sourceName }: ConferenceCardProps) {
  const minPrice = tiers.length ? Math.min(...tiers.map(t => t.price_gbp)) : null
  const maxPrice = tiers.length ? Math.max(...tiers.map(t => t.price_gbp)) : null
  const priceLabel = minPrice !== null
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

  const startFormatted = formatDate(c.start_date)
  const endFormatted = formatDate(c.end_date)
  const dateDisplay = startFormatted
    ? (endFormatted && c.end_date !== c.start_date
        ? `${startFormatted} – ${endFormatted}`
        : startFormatted)
    : 'Date TBC'

  const startTimeDisplay = formatTime(c.start_time)
  const formatBadge = c.event_format ? FORMAT_LABEL[c.event_format] : null
  const externalUrl = c.booking_url ?? c.organiser_url

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
          <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider truncate">
            {c.specialty || 'General'}
          </span>
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

        {(c.venue_name || c.city || formatBadge) && (
          <div className="flex items-center gap-2">
            {formatBadge ? (
              <formatBadge.Icon className="w-4 h-4 text-slate-500" />
            ) : (
              <MapPin className="w-4 h-4 text-slate-500" />
            )}
            <span>
              {[c.venue_name, c.city].filter(Boolean).join(', ') || formatBadge?.label}
            </span>
          </div>
        )}

        <div className="flex items-center gap-2">
          <PoundSterling className="w-4 h-4 text-slate-500" />
          <span className="font-medium text-white">{priceLabel}</span>
        </div>

        {c.abstract_open && (
          <div className="flex items-center gap-2 text-amber-400">
            <FileText className="w-4 h-4" />
            <span className="text-xs font-medium">Abstracts Open</span>
          </div>
        )}
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


