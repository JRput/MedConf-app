'use client'

import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import type { DirectoryFilters } from '@/lib/directory-query'
import type { FilterPatch } from './FilterControls'

/**
 * The four one-tap shortcuts the W2 brief calls out by name. Each toggles a
 * real filter field — clicking one twice returns to the previous state — so
 * there's no separate "quick filter" state to keep in sync with the sidebar.
 */
export function QuickFilterChips({ filters, onChange }: { filters: DirectoryFilters; onChange: (patch: FilterPatch) => void }) {
  const isThisMonth = filters.datePreset === 'this-month'
  const isOnline = filters.format.length === 1 && filters.format[0] === 'online'
  const isFree = filters.price === 'free'
  const isAbstractsOpen = filters.abstractsOpen

  return (
    <div className="flex flex-wrap gap-1.5">
      <Chip active={isThisMonth} onClick={() => onChange({ datePreset: isThisMonth ? null : 'this-month', dateFrom: null, dateTo: null })}>
        This month
      </Chip>
      <Chip active={isOnline} onClick={() => onChange({ format: isOnline ? [] : ['online'] })}>
        Online
      </Chip>
      <Chip active={isFree} onClick={() => onChange({ price: isFree ? 'any' : 'free' })}>
        Free
      </Chip>
      <Chip active={isAbstractsOpen} onClick={() => onChange({ abstractsOpen: !isAbstractsOpen })}>
        Abstracts open
      </Chip>
    </div>
  )
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Button variant={active ? 'subtle' : 'outline'} size="sm" aria-pressed={active} onClick={onClick}>
      {children}
    </Button>
  )
}
