'use client'

import type { DirectoryFacets, DirectoryFilters } from '@/lib/directory-query'
import { FilterControls, type FilterPatch } from './FilterControls'

/** Desktop-only (lg+), sticky — see FilterSheet.tsx for the mobile equivalent. */
export function FilterSidebar({
  filters,
  facets,
  onChange,
  onClearAll,
}: {
  filters: DirectoryFilters
  facets: DirectoryFacets | null
  onChange: (patch: FilterPatch) => void
  onClearAll: () => void
}) {
  return (
    <aside className="hidden w-[280px] shrink-0 lg:block">
      {/*
        No max-height/overflow here on purpose: the nested specialty/society
        Command lists each keep their own bounded `max-h` + `overflow-y-auto`
        (see FilterControls.tsx). Earlier this wrapper was ALSO scrollable,
        and cmdk's internal scrollIntoView-on-highlight calls would bubble up
        and auto-scroll this ancestor to a seemingly random position on first
        paint — a real bug, not a screenshot artifact. Letting the sidebar
        scroll with the page instead avoids the nested-scroll conflict.
      */}
      <div className="sticky top-[88px] rounded-lg border border-border bg-surface p-4">
        <FilterControls filters={filters} facets={facets} onChange={onChange} onClearAll={onClearAll} />
      </div>
    </aside>
  )
}
