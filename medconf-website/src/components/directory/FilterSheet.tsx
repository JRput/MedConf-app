'use client'

import * as React from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import type { DirectoryFacets, DirectoryFilters } from '@/lib/directory-query'
import { FilterControls, type FilterPatch } from './FilterControls'

/** Mobile/tablet (below lg) — the "Filters (n)" trigger + bottom sheet. */
export function FilterSheet({
  filters,
  facets,
  activeCount,
  onChange,
  onClearAll,
}: {
  filters: DirectoryFilters
  facets: DirectoryFacets | null
  activeCount: number
  onChange: (patch: FilterPatch) => void
  onClearAll: () => void
}) {
  const [open, setOpen] = React.useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Button variant="outline" size="sm" className="lg:hidden" onClick={() => setOpen(true)}>
        <SlidersHorizontal />
        Filters{activeCount > 0 ? ` (${activeCount})` : ''}
      </Button>
      <SheetContent side="bottom" className="max-h-[85vh] overflow-y-auto rounded-t-xl">
        <SheetHeader>
          <SheetTitle>Filters</SheetTitle>
          <SheetDescription className="sr-only">Narrow the conference directory by date, format, specialty and more.</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-4">
          <FilterControls filters={filters} facets={facets} onChange={onChange} onClearAll={onClearAll} />
        </div>
      </SheetContent>
    </Sheet>
  )
}
