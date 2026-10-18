import { FileText } from 'lucide-react'
import { DeadlineBadge } from '@/components/domain/DeadlineBadge'
import { hasAbstractInfo, isAbstractEffectivelyOpen } from '@/lib/conference-helpers'
import type { Conference } from '@/lib/types'
import type { FactField } from '@/lib/community/types'
import { CommunityTag } from '@/components/community/CommunityTag'

/** Abstract submission status — only renders when there's something to say. */
export function AbstractsBlock({
  conference,
  communityFields = [],
}: {
  conference: Conference
  /** Fields whose value came from the community overlay (see lib/community/overlay). */
  communityFields?: readonly FactField[]
}) {
  const fromCommunity = communityFields.some((f) => f === 'abstract_deadline' || f === 'abstract_deadline_note')
  if (!hasAbstractInfo(conference)) return null
  const open = isAbstractEffectivelyOpen(conference)

  return (
    <section className="space-y-2">
      <h2 className="type-h3 flex items-center gap-2 text-fg-strong">
        <FileText className="size-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
        Abstract submissions
        {fromCommunity && <CommunityTag />}
      </h2>
      <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-border bg-surface-muted px-4 py-3">
        <span className="type-body font-medium text-fg-strong">{open ? 'Open' : 'Closed'}</span>
        <DeadlineBadge
          deadline={conference.abstract_deadline}
          note={conference.abstract_deadline_note}
          showClosed
        />
        {conference.abstract_deadline_note && (
          <span className="type-small text-fg-muted">{conference.abstract_deadline_note}</span>
        )}
      </div>
    </section>
  )
}
