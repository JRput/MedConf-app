import { Building2, ExternalLink } from 'lucide-react'
import { SocietyChip } from '@/components/domain/SocietyChip'
import type { Conference, SourceSummary } from '@/lib/types'

/** The society/organiser attribution + a link out — kept separate from the
 *  sidebar's booking CTA, since "who published this" and "where do I book"
 *  are different questions. */
export function OrganiserBlock({
  conference,
  society,
}: {
  conference: Conference
  society: SourceSummary['society']
}) {
  if (!society && !conference.organiser_url) return null

  return (
    <section className="space-y-2">
      <h2 className="type-h3 flex items-center gap-2 text-fg-strong">
        <Building2 className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
        Organiser
      </h2>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface-muted px-4 py-3">
        {society ? (
          <SocietyChip name={society} className="type-body" />
        ) : (
          <span className="type-small text-fg-subtle">Independent organiser</span>
        )}
        {conference.organiser_url && (
          <a
            href={conference.organiser_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 type-small font-medium text-brand-text hover:underline"
          >
            Organiser&apos;s site
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        )}
      </div>
    </section>
  )
}
