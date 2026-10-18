'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import type { QueueItem } from '@/hooks/useModeration'
import { ageLabel } from '@/lib/community/moderation'
import { EnrichmentChip } from './EnrichmentChip'
import { SubmitterCell } from './SubmitterCell'

function KindBadge({ kind }: { kind: QueueItem['kind'] }) {
  return kind === 'new_event' ? <Badge variant="brand">New event</Badge> : <Badge variant="neutral">Add info</Badge>
}

const COLS = 'md:grid-cols-[6.5rem_minmax(0,1fr)_12rem_4.5rem_7rem]'

/** Dense queue: table-like grid at 768 px and up, stacked cards below. Rows are 44 px. */
export function QueueTable({ items }: { items: QueueItem[] }) {
  const router = useRouter()
  return (
    <div role="table" aria-label="Contributions" className="overflow-hidden rounded-lg border border-border bg-surface">
      <div role="row" className={`hidden items-center gap-3 border-b border-border bg-surface-muted px-4 py-2 md:grid ${COLS}`}>
        {['Kind', 'Event', 'Submitter', 'Age', 'Check'].map((h) => (
          <span key={h} role="columnheader" className="type-mono-label text-fg-subtle">
            {h}
          </span>
        ))}
      </div>
      <ul className="divide-y divide-border-subtle">
        {items.map((it) => (
          <li
            key={it.id}
            role="row"
            onClick={() => router.push(`/admin/moderation/${it.id}`)}
            className={`grid cursor-pointer grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 px-4 py-3 transition-colors duration-150 hover:bg-surface-hover md:min-h-11 md:gap-3 md:py-1.5 ${COLS}`}
          >
            <div role="cell" className="order-2 col-span-2 flex items-center gap-2 md:order-none md:col-span-1">
              <KindBadge kind={it.kind} />
              {it.status === 'merged' && <Badge variant="info">Merged</Badge>}
            </div>
            <div role="cell" className="order-1 min-w-0 md:order-none">
              <Link
                href={`/admin/moderation/${it.id}`}
                onClick={(e) => e.stopPropagation()}
                className="block truncate type-small font-medium text-fg-strong underline-offset-2 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {it.eventName}
              </Link>
            </div>
            <div role="cell" className="order-3 min-w-0 md:order-none">
              <SubmitterCell userId={it.user_id} submitter={it.submitter} />
            </div>
            <div role="cell" className="order-1 justify-self-end font-mono text-xs text-fg-muted md:order-none md:justify-self-start" title={new Date(it.created_at).toLocaleString()}>
              {ageLabel(it.created_at)}
            </div>
            <div role="cell" className="order-4 md:order-none">
              <EnrichmentChip status={it.enrichment_status} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
