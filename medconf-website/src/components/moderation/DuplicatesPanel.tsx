'use client'

import { useEffect, useMemo, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { duplicateCandidates, userFields, type DuplicateCandidate, type DuplicateRow } from '@/lib/community/moderation'
import { formatDateRange } from '@/lib/format'
import { searchDirectory } from './directory-search'

/**
 * Likely duplicates of a submitted event: same organiser site, or a similar
 * name starting within 30 days. Fetches the public directory by name.
 */
export function DuplicatesPanel({ payload, disabled, onMerge }: { payload: unknown; disabled?: boolean; onMerge: (row: DuplicateRow) => void }) {
  const name = useMemo(() => {
    const n = userFields(payload).conference_name
    return typeof n === 'string' ? n : ''
  }, [payload])
  const [rows, setRows] = useState<DuplicateRow[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    searchDirectory(name, ctl.signal)
      .then((r) => {
        setRows(r)
        setFailed(false)
      })
      .catch((e) => {
        if (e?.name !== 'AbortError') {
          setFailed(true)
          setRows([])
        }
      })
    return () => ctl.abort()
  }, [name])

  const candidates: DuplicateCandidate[] = useMemo(() => (rows ? duplicateCandidates(payload, rows) : []), [rows, payload])

  return (
    <section aria-labelledby="dups-title" className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <h2 id="dups-title" className="type-mono-label text-fg-muted">
          Possible duplicates
        </h2>
        {rows && <span className="font-mono text-xs text-fg-subtle">{candidates.length}</span>}
      </div>
      {rows === null ? (
        <p className="px-4 py-3 type-small text-fg-subtle">Checking the directory…</p>
      ) : failed ? (
        <p className="px-4 py-3 type-small text-warn-text">Could not search the directory. Check by hand before approving.</p>
      ) : candidates.length === 0 ? (
        <p className="px-4 py-3 type-small text-fg-muted">No likely duplicates found.</p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {candidates.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 md:min-h-11">
              <div className="min-w-0 flex-1">
                <a
                  href={`/conferences/${c.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-full items-center gap-1 type-small font-medium text-fg-strong underline-offset-2 hover:underline"
                >
                  <span className="truncate">{c.name}</span>
                  <ExternalLink className="size-3.5 shrink-0 text-fg-subtle" aria-hidden />
                </a>
                <p className="type-caption text-fg-muted">
                  #{c.id} · {formatDateRange(c.startDate, null)}
                  {c.city ? ` · ${c.city}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                {c.reasons.includes('same_domain') && <Badge variant="warning">Same site</Badge>}
                {c.reasons.includes('similar_name') && <Badge variant="warning">Similar name</Badge>}
              </div>
              <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => onMerge(c)}>
                Merge into this
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
