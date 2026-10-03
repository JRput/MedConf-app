'use client'

import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { DirectoryFilters } from '@/lib/directory-query'
import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'
import { societyInfo } from '@/lib/taxonomy/societies'
import type { FilterPatch } from './FilterControls'

const SPECIALTY_LABEL = new Map(SPECIALTY_PARENTS.map((p) => [p.slug, p.label]))
const FORMAT_LABEL: Record<string, string> = { in_person: 'In person', online: 'Online', hybrid: 'Hybrid' }
const TYPE_LABEL: Record<string, string> = { conference: 'Conference', course: 'Course', workshop: 'Workshop' }
const DATE_PRESET_LABEL: Record<string, string> = { 'this-month': 'This month', 'next-3-months': 'Next 3 months', 'this-year': 'This year' }
const PRICE_LABEL: Record<string, string> = { free: 'Free', 'under-100': 'Under £100', 'under-300': 'Under £300' }

interface Chip {
  key: string
  label: string
  remove: FilterPatch
}

function buildChips(f: DirectoryFilters): Chip[] {
  const chips: Chip[] = []

  if (f.q) chips.push({ key: 'q', label: `"${f.q}"`, remove: { q: '' } })

  if (f.datePreset) chips.push({ key: 'date', label: DATE_PRESET_LABEL[f.datePreset], remove: { datePreset: null } })
  else if (f.dateFrom || f.dateTo) chips.push({ key: 'date', label: 'Custom dates', remove: { dateFrom: null, dateTo: null } })

  for (const v of f.format) chips.push({ key: `format:${v}`, label: FORMAT_LABEL[v] ?? v, remove: { format: f.format.filter((x) => x !== v) } })
  for (const v of f.type) chips.push({ key: `type:${v}`, label: TYPE_LABEL[v] ?? v, remove: { type: f.type.filter((x) => x !== v) } })
  for (const v of f.specialty) chips.push({ key: `spec:${v}`, label: SPECIALTY_LABEL.get(v) ?? v, remove: { specialty: f.specialty.filter((x) => x !== v) } })
  for (const v of f.region) chips.push({ key: `region:${v}`, label: v, remove: { region: f.region.filter((x) => x !== v) } })

  if (f.country) chips.push({ key: 'country', label: f.country === 'uk' ? 'UK' : 'International', remove: { country: null } })
  if (f.price !== 'any') chips.push({ key: 'price', label: PRICE_LABEL[f.price] ?? f.price, remove: { price: 'any' } })
  for (const v of f.society) chips.push({ key: `soc:${v}`, label: societyInfo(v)?.name ?? v, remove: { society: f.society.filter((x) => x !== v) } })

  if (f.cpd) chips.push({ key: 'cpd', label: 'CPD accredited', remove: { cpd: false } })
  if (f.abstractsOpen) chips.push({ key: 'abstracts', label: 'Abstracts open', remove: { abstractsOpen: false } })

  return chips
}

export function ActiveFilterChips({ filters, onChange }: { filters: DirectoryFilters; onChange: (patch: FilterPatch) => void }) {
  const chips = buildChips(filters)
  if (!chips.length) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="list" aria-label="Active filters">
      {chips.map((chip) => (
        <Button key={chip.key} variant="subtle" size="xs" className="rounded-full pr-1.5" onClick={() => onChange(chip.remove)} role="listitem">
          {chip.label}
          <X className="size-3" aria-hidden />
          <span className="sr-only">Remove filter: {chip.label}</span>
        </Button>
      ))}
    </div>
  )
}
