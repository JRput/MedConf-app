'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/utils'
import { duplicateQuery, flagDuplicates, shouldCheckDuplicates, toMatches, type FlaggedMatch } from './logic'

interface Result {
  /** The query this result answers, so a stale result is never shown for a newer query. */
  q: string
  matches: FlaggedMatch[] | null // null = request failed
}

/**
 * Debounced (400 ms) look-up against the public directory. A warning, never a
 * block: the submitter can always carry on. Matches that share the typed
 * organiser's domain are flagged as likely duplicates.
 */
export function DuplicateCheck({ name, organiserUrl }: { name: string; organiserUrl: string }) {
  const debounced = useDebouncedValue({ name, organiserUrl }, 400)
  const q = shouldCheckDuplicates(debounced.name, debounced.organiserUrl) ? duplicateQuery(debounced.name, debounced.organiserUrl) : null
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    if (!q) return
    const ctrl = new AbortController()
    fetch(`/api/directory?q=${encodeURIComponent(q)}&pageSize=5`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((json: { rows?: unknown }) => {
        setResult({ q, matches: flagDuplicates(toMatches(json.rows), debounced.organiserUrl) })
      })
      .catch((e: unknown) => {
        if ((e as { name?: string })?.name === 'AbortError') return
        setResult({ q, matches: null })
      })
    return () => ctrl.abort()
  }, [q, debounced.organiserUrl])

  if (!q) return null

  if (!result || result.q !== q) {
    return (
      <p className="flex items-center gap-2 type-caption text-fg-subtle" role="status">
        <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
        Checking whether this event is already listed
      </p>
    )
  }
  if (result.matches === null) return null
  const state = { matches: result.matches }

  if (state.matches.length === 0) return null
  const same = state.matches.filter((m) => m.sameSite)

  return (
    <div
      role="status"
      className={cn(
        'space-y-3 rounded-lg border p-3.5',
        same.length > 0 ? 'border-warn-border bg-warn-subtle' : 'border-border bg-surface-muted'
      )}
    >
      {same.length > 0 && (
        <p className="flex items-start gap-2 type-small font-medium text-fg-strong">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden />
          Looks like this event is already listed. Add info to it instead.
        </p>
      )}
      <div>
        <p className="mb-1.5 type-caption font-medium text-fg-muted">
          {same.length > 0 ? 'Matching listings' : 'Similar events already listed'}
        </p>
        <ul className="space-y-1">
          {state.matches.map((m) => (
            <li key={m.id}>
              <Link
                href={`/conferences/${m.id}`}
                target="_blank"
                rel="noopener"
                className="flex min-h-11 cursor-pointer items-center justify-between gap-3 rounded-md px-2 type-small text-brand-text underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring [@media(hover:hover)_and_(pointer:fine)]:hover:underline"
              >
                <span className="min-w-0 truncate">{m.name}</span>
                <span className="shrink-0 type-caption text-fg-subtle">
                  {m.sameSite ? 'Same organiser site' : (m.startDate ?? '')}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
      <p className="type-caption text-fg-subtle">This is only a warning. You can still submit if yours is a different event.</p>
    </div>
  )
}
