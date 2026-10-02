'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { Clock, Search, Stethoscope, Users } from 'lucide-react'
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'
import { SOCIETIES } from '@/lib/taxonomy/societies'
import type { DirectoryEvent } from '@/lib/directory'

const RECENTS_KEY = 'medconf:recent-searches'
const RECENTS_MAX = 5

function readRecents(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENTS_KEY) ?? '[]')
  } catch {
    return []
  }
}
function pushRecent(term: string) {
  try {
    const next = [term, ...readRecents().filter((t) => t !== term)].slice(0, RECENTS_MAX)
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next))
  } catch {
    // localStorage can throw in private mode — a lost recent-search entry isn't worth a crash.
  }
}

/**
 * Global ⌘K / Ctrl-K palette: jump straight to a title, a specialty or a
 * society without going through the sidebar. Self-contained — mount it once
 * near the top of the directory page; it owns its own open state and the
 * global key listener.
 */
export function CommandPalette({ fixture = false }: { fixture?: boolean }) {
  const router = useRouter()
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const [results, setResults] = React.useState<DirectoryEvent[]>([])
  const [recents, setRecents] = React.useState<string[]>([])
  const debouncedQuery = useDebouncedValue(query, 250)

  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  React.useEffect(() => {
    if (open) setRecents(readRecents())
  }, [open])

  React.useEffect(() => {
    if (!debouncedQuery.trim()) {
      setResults([])
      return
    }
    const controller = new AbortController()
    const params = new URLSearchParams({ q: debouncedQuery, pageSize: '6' })
    if (fixture) params.set('fixture', '1')
    fetch(`/api/directory?${params.toString()}`, { signal: controller.signal })
      .then((r) => r.json())
      .then((data) => setResults(Array.isArray(data.rows) ? data.rows : []))
      .catch(() => {})
    return () => controller.abort()
  }, [debouncedQuery, fixture])

  function goTo(href: string, recent?: string) {
    setOpen(false)
    if (recent) pushRecent(recent)
    router.push(href)
  }

  const specialtyMatches = query.trim()
    ? SPECIALTY_PARENTS.filter((p) => p.label.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 5)
    : []
  const societyMatches = query.trim()
    ? Object.values(SOCIETIES)
        .filter((s) => s.name.toLowerCase().includes(query.trim().toLowerCase()))
        .slice(0, 5)
    : []

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title="Search the directory" description="Search by title, specialty or society">
      <CommandInput placeholder="Search events, specialties or societies…" value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>No matches.</CommandEmpty>

        {!query.trim() && recents.length > 0 && (
          <CommandGroup heading="Recent searches">
            {recents.map((term) => (
              <CommandItem key={term} value={term} onSelect={() => goTo(`/conferences?q=${encodeURIComponent(term)}`, term)}>
                <Clock />
                {term}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {results.length > 0 && (
          <CommandGroup heading="Events">
            {results.map((event) => (
              <CommandItem key={event.id} value={event.name} onSelect={() => goTo(event.href, query.trim())}>
                <Search />
                <span className="truncate">{event.name}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {specialtyMatches.length > 0 && (
          <CommandGroup heading="Specialties">
            {specialtyMatches.map((p) => (
              <CommandItem key={p.slug} value={p.label} onSelect={() => goTo(`/conferences?specialty=${p.slug}`)}>
                <Stethoscope />
                {p.label}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {societyMatches.length > 0 && (
          <CommandGroup heading="Societies">
            {societyMatches.map((s) => (
              <CommandItem key={s.short} value={s.name} onSelect={() => goTo(`/conferences?society=${s.short}`)}>
                <Users />
                {s.name}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  )
}
