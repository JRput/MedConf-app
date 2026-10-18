'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FeeQuickEditor } from '@/components/community/FeeQuickEditor'
import type { FeesDraft } from '@/lib/community/fees-draft'
import { currencySymbol } from '@/lib/conference-helpers'
import { foundTiers } from '@/lib/community/moderation'
import type { Contribution, FeesPayload } from '@/lib/community/types'
import { cn } from '@/lib/utils'

function TierList({ fees }: { fees: { currency: string; from_price?: number; tiers: { label: string; price: number; is_early_bird: boolean }[] } | null | undefined }) {
  if (!fees || (fees.tiers.length === 0 && fees.from_price == null)) return <span className="text-fg-subtle">None</span>
  const sym = currencySymbol(fees.currency)
  return (
    <ul className="space-y-0.5">
      {fees.from_price != null && fees.tiers.length === 0 && <li className="type-small">From {sym}{fees.from_price}</li>}
      {fees.tiers.map((t, i) => (
        <li key={i} className="flex items-baseline justify-between gap-3 type-small">
          <span className="truncate">
            {t.label}
            {t.is_early_bird ? ' (early bird)' : ''}
          </span>
          <span className="font-mono text-xs">
            {sym}
            {t.price}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Fees: what the user entered, what the organiser site showed, and the editable final list. */
export function TierReviewTable({
  userFees,
  enrichment,
  draft,
  onDraft,
  prefilled,
  disagrees,
  onKeep,
}: {
  userFees: FeesPayload | undefined
  enrichment: Contribution['enrichment']
  draft: FeesDraft
  onDraft: (d: FeesDraft) => void
  /** Final currently holds organiser-site fees the moderator has not yet confirmed. */
  prefilled: boolean
  disagrees: boolean
  onKeep: () => void
}) {
  const found = foundTiers(enrichment)
  return (
    <div className={cn('overflow-hidden rounded-lg border border-border bg-surface', disagrees && 'border-warn-border')}>
      <div className={cn('grid gap-px bg-border-subtle md:grid-cols-2', disagrees && 'bg-warn-border')}>
        <div className={cn('space-y-1.5 bg-surface p-4', disagrees && 'bg-warn-subtle')}>
          <p className="type-mono-label text-fg-subtle">User entered</p>
          <TierList fees={userFees} />
        </div>
        <div className={cn('space-y-1.5 bg-surface p-4', disagrees && 'bg-warn-subtle')}>
          <div className="flex items-center gap-2">
            <p className="type-mono-label text-fg-subtle">Found on organiser site</p>
            {disagrees && <Badge variant="warning">Differs</Badge>}
          </div>
          {found ? (
            <>
              <TierList fees={found} />
              <p className="type-caption text-fg-subtle">{found.method.replace(/_/g, ' ')}</p>
            </>
          ) : (
            <span className="type-small text-fg-subtle">{enrichment ? 'Not found' : 'Not checked'}</span>
          )}
        </div>
      </div>
      <div className="space-y-3 border-t border-border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="type-mono-label text-fg-muted">Final</p>
          {prefilled && (
            <div className="flex items-center gap-2">
              <Badge variant="info">From organiser site</Badge>
              <Button type="button" variant="ghost" size="xs" onClick={onKeep}>
                Keep
              </Button>
            </div>
          )}
        </div>
        <FeeQuickEditor value={draft} onChange={onDraft} idPrefix="mod-fees" />
      </div>
    </div>
  )
}
