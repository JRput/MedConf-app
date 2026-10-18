'use client'

import { useEffect, useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { formatDateRange } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DuplicateRow } from '@/lib/community/moderation'
import { searchDirectory } from './directory-search'

/**
 * Pick the existing listing to merge a contribution into. Preselect a
 * duplicate candidate, or search the directory freely.
 */
export function MergePicker({
  open,
  onOpenChange,
  preselected,
  initialQuery,
  busy,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  preselected: DuplicateRow | null
  initialQuery: string
  busy: boolean
  onConfirm: (conferenceId: number) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] gap-4 overflow-y-auto bg-surface p-5 sm:max-w-lg sm:p-6">
        {/* Mounted only while open, so each opening starts from its own candidate and query. */}
        {open && (
          <PickerBody
            preselected={preselected}
            initialQuery={initialQuery}
            busy={busy}
            onCancel={() => onOpenChange(false)}
            onConfirm={onConfirm}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function PickerBody({
  preselected,
  initialQuery,
  busy,
  onCancel,
  onConfirm,
}: {
  preselected: DuplicateRow | null
  initialQuery: string
  busy: boolean
  onCancel: () => void
  onConfirm: (conferenceId: number) => void
}) {
  const [query, setQuery] = useState(preselected?.name ?? initialQuery)
  const [picked, setPicked] = useState<DuplicateRow | null>(preselected)
  const [found, setFound] = useState<{ q: string; rows: DuplicateRow[] }>({ q: '\u0000', rows: [] })
  const debounced = useDebouncedValue(query, 250)
  const searching = found.q !== debounced

  useEffect(() => {
    const ctl = new AbortController()
    searchDirectory(debounced, ctl.signal, 10)
      .then((rows) => setFound({ q: debounced, rows }))
      .catch((e) => {
        if (e?.name !== 'AbortError') setFound({ q: debounced, rows: [] })
      })
    return () => ctl.abort()
  }, [debounced])

  const list = picked && !found.rows.some((r) => r.id === picked.id) ? [picked, ...found.rows] : found.rows

  return (
    <>
      <DialogHeader>
        <DialogTitle className="type-h3 text-fg-strong">Merge into an existing listing</DialogTitle>
        <DialogDescription className="type-small text-fg-muted">
          The details become community information on that listing. No new event is created.
        </DialogDescription>
      </DialogHeader>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <Input aria-label="Search the directory" className="h-11 pl-9" placeholder="Search by event name" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      <ul role="listbox" aria-label="Matching listings" className="max-h-72 divide-y divide-border-subtle overflow-y-auto rounded-md border border-border">
        {list.length === 0 && (
          <li className="px-3 py-4 text-center type-small text-fg-muted">{searching ? 'Searching…' : query.trim().length < 2 ? 'Type at least two letters.' : 'No listings found.'}</li>
        )}
        {list.map((r) => {
          const active = picked?.id === r.id
          return (
            <li key={r.id} role="option" aria-selected={active}>
              <button
                type="button"
                onClick={() => setPicked(r)}
                className={cn(
                  'flex min-h-11 w-full cursor-pointer flex-col items-start px-3 py-2 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                  active ? 'bg-brand-subtle' : 'hover:bg-surface-hover'
                )}
              >
                <span className={cn('type-small font-medium', active ? 'text-brand-text' : 'text-fg-strong')}>{r.name}</span>
                <span className="type-caption text-fg-muted">
                  #{r.id} · {formatDateRange(r.startDate, null)}
                  {r.city ? ` · ${r.city}` : ''}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <DialogFooter className="gap-2">
        <Button type="button" variant="ghost" size="lg" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="button" size="lg" disabled={!picked || busy} aria-busy={busy} onClick={() => picked && onConfirm(picked.id)}>
          {busy ? (
            <>
              <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
              Merging…
            </>
          ) : picked ? (
            `Merge into #${picked.id}`
          ) : (
            'Choose a listing'
          )}
        </Button>
      </DialogFooter>
    </>
  )
}
