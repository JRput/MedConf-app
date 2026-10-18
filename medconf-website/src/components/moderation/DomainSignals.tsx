'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, Info } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { domainLabel, domainSignals, type DuplicateRow } from '@/lib/community/moderation'
import { searchDirectory } from './directory-search'

/**
 * Links block for the item header: organiser and booking domains, a mismatch
 * warning, a "not seen in the directory" warning (heuristic), and a reminder
 * that organiser-site findings come from a page the submitter may control.
 */
export function DomainSignals({ finalPayload }: { finalPayload: unknown }) {
  const base = domainSignals(finalPayload, null)
  const label = domainLabel(base.organiserDomain)
  const [hits, setHits] = useState<{ label: string; rows: DuplicateRow[] } | null>(null)

  useEffect(() => {
    if (!label) return
    const ctl = new AbortController()
    searchDirectory(label, ctl.signal, 20)
      .then((rows) => setHits({ label, rows }))
      .catch(() => {})
    return () => ctl.abort()
  }, [label])

  const sig = domainSignals(finalPayload, hits && hits.label === label ? hits.rows : null)
  if (!sig.organiserDomain && !sig.bookingDomain) return null

  return (
    <section aria-label="Links" className="space-y-2 rounded-lg border border-border bg-surface px-4 py-3">
      <p className="type-mono-label text-fg-subtle">Links</p>
      <dl className="grid gap-x-6 gap-y-1 type-small sm:grid-cols-2">
        <div className="flex gap-2">
          <dt className="text-fg-muted">Organiser</dt>
          <dd className="font-mono text-xs text-fg">{sig.organiserDomain ?? 'None'}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-fg-muted">Booking</dt>
          <dd className="font-mono text-xs text-fg">{sig.bookingDomain ?? 'None'}</dd>
        </div>
      </dl>
      {sig.mismatch && (
        <Warn>The booking link is on a different domain from the organiser page. Check that both belong to the same organiser.</Warn>
      )}
      {sig.unseen === true && (
        <Warn>
          Domain not seen in the directory before.
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" aria-label="How this is worked out" className="ml-1.5 inline-flex size-6 cursor-pointer items-center justify-center rounded-sm align-middle text-warn-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <Info className="size-3.5" aria-hidden />
              </button>
            </TooltipTrigger>
            <TooltipContent>Heuristic: no directory listing found by searching the domain name has an organiser link on this domain. It is not proof the domain is new.</TooltipContent>
          </Tooltip>
        </Warn>
      )}
      <p className="flex items-start gap-2 type-caption text-fg-muted">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Values marked &ldquo;found on organiser site&rdquo; come from a page the submitter may control. A match is not proof.
      </p>
    </section>
  )
}

function Warn({ children }: { children: React.ReactNode }) {
  return (
    <p role="status" className="flex items-start gap-2 rounded-md border border-warn-border bg-warn-subtle px-3 py-2 type-small text-warn-text">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  )
}
