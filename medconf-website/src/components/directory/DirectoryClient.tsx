'use client'

import * as React from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { parseDirectoryUrl, serializeDirectoryFilters } from '@/lib/directory-url'
import type { DirectoryFacets, DirectoryFilters, DirectoryPage, DirectorySort } from '@/lib/directory-query'
import { SOCIETIES } from '@/lib/taxonomy/societies'
import { useSaved } from '@/hooks/useSaved'
import { SearchInput } from './SearchInput'
import { QuickFilterChips } from './QuickFilterChips'
import { ActiveFilterChips } from './ActiveFilterChips'
import { FilterSidebar } from './FilterSidebar'
import { FilterSheet } from './FilterSheet'
import { SortMenu } from './SortMenu'
import { ResultsList } from './ResultsList'
import { Pagination } from './Pagination'
import { CommandPalette } from './CommandPalette'
import type { FilterPatch } from './FilterControls'

interface DirectoryData {
  rows: DirectoryPage['rows']
  total: number
  page: number
  pageSize: number
  facets: DirectoryFacets | null
}

/**
 * Owns all directory interaction state. The FIRST page is server-rendered by
 * app/conferences/page.tsx straight off `queryDirectory`/`queryFacets` (fast,
 * indexable); every filter/sort/page change after that goes through this
 * client component, which re-fetches via /api/directory and pushes the new
 * state into the URL so links stay shareable.
 */
export function DirectoryClient({
  initialFilters,
  initialData,
  fixture,
}: {
  initialFilters: DirectoryFilters
  initialData: DirectoryData
  fixture: boolean
}) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [isPending, startTransition] = React.useTransition()
  const { savedIds, toggleSave } = useSaved()

  const filters = React.useMemo(() => parseDirectoryUrl(searchParams), [searchParams])

  const [data, setData] = React.useState<DirectoryData>(initialData)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const lastKeyRef = React.useRef(JSON.stringify(initialFilters))
  const abortRef = React.useRef<AbortController | null>(null)

  React.useEffect(() => {
    const key = JSON.stringify(filters)
    if (key === lastKeyRef.current) return
    lastKeyRef.current = key

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    const params = serializeDirectoryFilters(filters)
    params.set('facets', '1')
    if (fixture) params.set('fixture', '1')

    fetch(`/api/directory?${params.toString()}`, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`Request failed (${r.status})`)
        return r.json()
      })
      .then((json: { rows: DirectoryPage['rows']; total: number; page: number; pageSize: number; facets: DirectoryFacets | null; error?: string }) => {
        if (json.error) throw new Error(json.error)
        setData({ rows: json.rows, total: json.total, page: json.page, pageSize: json.pageSize, facets: json.facets })
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Something went wrong loading the directory.')
        setLoading(false)
      })

    return () => controller.abort()
  }, [filters, fixture])

  function navigate(next: DirectoryFilters) {
    const params = serializeDirectoryFilters(next)
    const qs = params.toString()
    startTransition(() => {
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    })
  }

  function patch(p: FilterPatch) {
    const next: DirectoryFilters = { ...filters, ...p }
    if (!('page' in p)) next.page = 1
    navigate(next)
  }

  function clearAll() {
    navigate({ ...filters, q: '', dateFrom: null, dateTo: null, datePreset: null, format: [], type: [], specialty: [], region: [], country: null, price: 'any', society: [], cpd: false, abstractsOpen: false, sort: filters.sort, page: 1 })
  }

  const activeFilterCount = countSidebarFilters(filters)
  const societyCount = Object.keys(SOCIETIES).length

  return (
    <div className="mx-auto max-w-[1320px] px-4 pb-20 sm:px-6">
      <CommandPalette fixture={fixture} />

      <header className="border-b border-border py-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="type-h1 text-fg-strong">Conference directory</h1>
          <p className="type-mono-label text-fg-subtle">
            {data.total.toLocaleString()} event{data.total === 1 ? '' : 's'} · {societyCount} societies
          </p>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <SearchInput value={filters.q} onChange={(q) => patch({ q })} className="w-full sm:max-w-sm" />
          <QuickFilterChips filters={filters} onChange={patch} />
        </div>
      </header>

      <div className="flex flex-col gap-6 pt-6 lg:flex-row">
        <FilterSidebar filters={filters} facets={data.facets} onChange={patch} onClearAll={clearAll} />

        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <FilterSheet filters={filters} facets={data.facets} activeCount={activeFilterCount} onChange={patch} onClearAll={clearAll} />
              <ActiveFilterChips filters={filters} onChange={patch} />
            </div>
            <SortMenu value={filters.sort} onChange={(sort: DirectorySort) => patch({ sort })} />
          </div>

          <ResultsList
            rows={data.rows}
            loading={loading || isPending}
            error={error}
            facets={data.facets}
            savedIds={savedIds}
            onToggleSave={(id) => toggleSave(id)}
            onClearAll={clearAll}
            onBroadenDate={() => patch({ datePreset: null, dateFrom: null, dateTo: null })}
            hasDateFilter={!!(filters.datePreset || filters.dateFrom || filters.dateTo)}
            onRetry={() => navigate(filters)}
          />

          <div className="mt-6">
            <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onChange={(page) => patch({ page })} />
          </div>
        </div>
      </div>
    </div>
  )
}

function countSidebarFilters(f: DirectoryFilters): number {
  let n = 0
  if (f.datePreset || f.dateFrom || f.dateTo) n++
  if (f.format.length) n++
  if (f.type.length) n++
  if (f.specialty.length) n++
  if (f.region.length) n++
  if (f.country) n++
  if (f.price !== 'any') n++
  if (f.society.length) n++
  if (f.cpd) n++
  if (f.abstractsOpen) n++
  return n
}
