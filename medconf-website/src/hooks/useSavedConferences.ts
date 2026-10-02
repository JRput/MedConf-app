// src/hooks/useSavedConferences.ts
//
// Shared "saved event" data hook for /dashboard and /saved — replaces the
// bespoke fetch/pagination/grouping block that used to live inline in
// app/saved/page.tsx (see ../../../reports/website-audit/code.md §2 item 3,
// refactor list item 2). Built on useSaved() for the id set, then resolves
// those ids against the same `directory_events` view the public directory
// reads from, via directoryEventFromRow() — so a saved row renders with
// exactly the same view-model (DirectoryEvent) as everywhere else.
//
// Only ids not already resolved are fetched, and a toggled-off id is just
// dropped from the derived `events` list rather than refetched — so saving
// one more event, or unsaving one, never re-downloads events already known.

import { useEffect, useMemo, useRef, useState } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import { useSaved } from '@/hooks/useSaved'
import { directoryEventFromRow, type DirectoryEvent, type DirectoryEventRow } from '@/lib/directory'

export function useSavedConferences() {
  const { user } = useAuth()
  const { savedIds, isSaved, toggleSave } = useSaved()
  const supabase = createSupabaseClient()
  const [eventsById, setEventsById] = useState<Record<number, DirectoryEvent>>({})
  const [loading, setLoading] = useState(true)
  const fetchedIds = useRef<Set<number>>(new Set())

  useEffect(() => {
    if (!user) {
      setEventsById({})
      fetchedIds.current = new Set()
      setLoading(false)
      return
    }

    const missing = Array.from(savedIds).filter((id) => !fetchedIds.current.has(id))
    if (missing.length === 0) {
      setLoading(false)
      return
    }

    setLoading(true)

    // NOTE: `missing` ids are marked as fetched only once the request
    // actually resolves, not before firing it — marking them up front (and
    // guarding the `.then()` with a `cancelled` flag set in this effect's
    // cleanup) looks like standard abort-on-cleanup practice, but React 18
    // Strict Mode's dev-only mount→cleanup→remount means the cleanup from
    // this FIRST invocation fires before the request resolves, while the
    // SECOND invocation would then see those ids as already "fetched" and
    // skip refetching them — permanently dropping the result. Fetching the
    // same ids twice in dev is harmless; losing them forever is not.
    supabase
      .from('directory_events')
      .select('*')
      .in('id', missing)
      .then(({ data, error }) => {
        if (!error && data) {
          const rows = data as DirectoryEventRow[]
          rows.forEach((row) => fetchedIds.current.add(row.id))
          setEventsById((prev) => {
            const next = { ...prev }
            rows.forEach((row) => {
              next[row.id] = directoryEventFromRow(row)
            })
            return next
          })
        }
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, savedIds])

  const events = useMemo(
    () =>
      Array.from(savedIds)
        .map((id) => eventsById[id])
        .filter((e): e is DirectoryEvent => Boolean(e)),
    [savedIds, eventsById]
  )

  return { events, loading: loading && events.length === 0, isSaved, toggleSave, savedIds }
}
