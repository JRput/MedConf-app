'use client'

import * as React from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DatePreset, DirectoryFacets, DirectoryFilters, DirectoryFormat, DirectoryType, PriceFilter } from '@/lib/directory-query'
import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'
import { societiesByKind, type SocietyKind } from '@/lib/taxonomy/societies'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Calendar } from '@/components/ui/calendar'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'

const FORMAT_OPTIONS: { value: DirectoryFormat; label: string }[] = [
  { value: 'in_person', label: 'In person' },
  { value: 'online', label: 'Online' },
  { value: 'hybrid', label: 'Hybrid' },
]
const TYPE_OPTIONS: { value: DirectoryType; label: string }[] = [
  { value: 'conference', label: 'Conference' },
  { value: 'course', label: 'Course' },
  { value: 'workshop', label: 'Workshop' },
]
const DATE_PRESETS: { value: DatePreset; label: string }[] = [
  { value: 'this-month', label: 'This month' },
  { value: 'next-3-months', label: 'Next 3 months' },
  { value: 'this-year', label: 'This year' },
]
const PRICE_OPTIONS: { value: PriceFilter; label: string }[] = [
  { value: 'any', label: 'Any' },
  { value: 'free', label: 'Free' },
  { value: 'under-100', label: 'Under £100' },
  { value: 'under-300', label: 'Under £300' },
]
const SOCIETY_KIND_LABEL: Record<SocietyKind, string> = {
  'royal-college': 'Royal Colleges & Faculties',
  faculty: 'Royal Colleges & Faculties',
  specialist: 'Specialist societies',
  international: 'International societies',
  defence: 'Medical defence',
  other: 'Other',
}
const SOCIETY_KIND_ORDER: SocietyKind[] = ['royal-college', 'international', 'specialist', 'defence', 'other']

export type FilterPatch = Partial<DirectoryFilters>

/**
 * The single filter surface — shared verbatim between the desktop sticky
 * sidebar and the mobile bottom sheet (see FilterSidebar.tsx / FilterSheet.tsx)
 * so the two can never drift into "two places to set the same filter", the
 * #2 finding in the UX audit this mission is fixing.
 *
 * No Checkbox/Switch/RadioGroup primitive exists yet in the W1 kit, so the
 * checkbox-row and switch-row controls below are built from Button/div +
 * existing tokens rather than introducing new colours or components.
 */
export function FilterControls({
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
  const [customRange, setCustomRange] = React.useState<{ from?: Date; to?: Date }>({})
  const [specialtyQuery, setSpecialtyQuery] = React.useState('')
  const [societyQuery, setSocietyQuery] = React.useState('')
  // cmdk auto-highlights the first item on mount and calls
  // `scrollIntoView({block:'nearest'})` on it — harmless for a palette near
  // the top of the viewport, but these two lists sit deep in a tall sidebar,
  // so that call walked all the way up to the WINDOW and yanked the whole
  // page's scroll position on first paint. Controlling `value` with a
  // sentinel that matches no real item is cmdk's documented workaround:
  // it skips the auto-select-first-item effect (and the scroll it causes)
  // entirely, while leaving click-to-select untouched (onSelect fires from
  // onClick, independent of this state).
  const [specialtyActive, setSpecialtyActive] = React.useState('__none__')
  const [societyActive, setSocietyActive] = React.useState('__none__')

  const activeCount = countActive(filters)
  const societyGroups = React.useMemo(() => societiesByKind(), [])

  function toggleInArray(key: 'format' | 'type' | 'specialty' | 'region' | 'society', value: string) {
    const current = filters[key] as string[]
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    onChange({ [key]: next } as FilterPatch)
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="type-mono-label text-fg-subtle">Filters</h2>
        {activeCount > 0 && (
          <Button variant="ghost" size="xs" onClick={onClearAll}>
            Clear all
          </Button>
        )}
      </div>

      {/* --------------------------------------------------------- Date */}
      <Section title="Date">
        <ToggleGroup
          type="single"
          variant="outline"
          className="w-full flex-wrap"
          value={filters.datePreset ?? (filters.dateFrom || filters.dateTo ? 'custom' : 'any')}
          onValueChange={(v) => {
            if (!v || v === 'any') onChange({ datePreset: null, dateFrom: null, dateTo: null })
            else if (v === 'custom') onChange({ datePreset: null })
            else onChange({ datePreset: v as DatePreset, dateFrom: null, dateTo: null })
          }}
        >
          <ToggleGroupItem value="any">Any</ToggleGroupItem>
          {DATE_PRESETS.map((p) => (
            <ToggleGroupItem key={p.value} value={p.value}>
              {p.label}
            </ToggleGroupItem>
          ))}
          <Popover>
            <PopoverTrigger asChild>
              <ToggleGroupItem value="custom">Custom</ToggleGroupItem>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="range"
                selected={{ from: customRange.from ?? parseIso(filters.dateFrom), to: customRange.to ?? parseIso(filters.dateTo) }}
                onSelect={(range) => {
                  setCustomRange({ from: range?.from, to: range?.to })
                  onChange({
                    datePreset: null,
                    dateFrom: range?.from ? toIso(range.from) : null,
                    dateTo: range?.to ? toIso(range.to) : null,
                  })
                }}
              />
            </PopoverContent>
          </Popover>
        </ToggleGroup>
      </Section>

      <Separator />

      {/* ------------------------------------------------------- Format */}
      <Section title="Format">
        <ToggleGroup
          type="multiple"
          variant="outline"
          className="w-full flex-wrap"
          value={filters.format}
          onValueChange={(v) => onChange({ format: v as DirectoryFormat[] })}
        >
          {FORMAT_OPTIONS.map((o) => (
            <ToggleGroupItem key={o.value} value={o.value}>
              {o.label}
              <FacetCount n={facets?.format[o.value]} />
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Section>

      <Separator />

      {/* --------------------------------------------------------- Type */}
      <Section title="Type">
        <ToggleGroup
          type="multiple"
          variant="outline"
          className="w-full flex-wrap"
          value={filters.type}
          onValueChange={(v) => onChange({ type: v as DirectoryType[] })}
        >
          {TYPE_OPTIONS.map((o) => (
            <ToggleGroupItem key={o.value} value={o.value}>
              {o.label}
              <FacetCount n={facets?.type[o.value]} />
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Section>

      <Separator />

      {/* ---------------------------------------------------- Specialty */}
      <Section title="Specialty">
        <Command className="rounded-md border border-border" shouldFilter value={specialtyActive} onValueChange={setSpecialtyActive}>
          <CommandInput placeholder="Search specialties…" value={specialtyQuery} onValueChange={setSpecialtyQuery} />
          <CommandList className="max-h-56">
            <CommandEmpty>No matches.</CommandEmpty>
            <CommandGroup>
              {SPECIALTY_PARENTS.filter((p) => (facets ? facets.specialty[p.slug] > 0 || filters.specialty.includes(p.slug) : true)).map((p) => {
                const checked = filters.specialty.includes(p.slug)
                return (
                  <CommandItem key={p.slug} value={p.label} onSelect={() => toggleInArray('specialty', p.slug)}>
                    <CheckBox checked={checked} />
                    <span className="flex-1 truncate">{p.label}</span>
                    <FacetCount n={facets?.specialty[p.slug]} />
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </Section>

      <Separator />

      {/* ------------------------------------------------- Region / country */}
      <Section title="Region">
        <ToggleGroup
          type="single"
          variant="outline"
          className="w-full"
          value={filters.country ?? 'all'}
          onValueChange={(v) => onChange({ country: v === 'all' ? null : (v as 'uk' | 'international') })}
        >
          <ToggleGroupItem value="all" className="flex-1">
            All
          </ToggleGroupItem>
          <ToggleGroupItem value="uk" className="flex-1">
            UK
            <FacetCount n={facets?.country.uk} />
          </ToggleGroupItem>
          <ToggleGroupItem value="international" className="flex-1">
            International
            <FacetCount n={facets?.country.international} />
          </ToggleGroupItem>
        </ToggleGroup>

        {facets && Object.keys(facets.region).length > 0 && (
          <div className="mt-2 max-h-48 space-y-0.5 overflow-y-auto rounded-md border border-border p-1">
            {Object.entries(facets.region)
              .sort((a, b) => b[1] - a[1])
              .map(([region, count]) => (
                <CheckRow key={region} label={region} count={count} checked={filters.region.includes(region)} onToggle={() => toggleInArray('region', region)} />
              ))}
          </div>
        )}
      </Section>

      <Separator />

      {/* ------------------------------------------------------- Price */}
      <Section title="Price">
        <ToggleGroup
          type="single"
          variant="outline"
          className="w-full flex-wrap"
          value={filters.price}
          onValueChange={(v) => v && onChange({ price: v as PriceFilter })}
        >
          {PRICE_OPTIONS.map((o) => (
            <ToggleGroupItem key={o.value} value={o.value}>
              {o.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {typeof facets?.priceBucket.unknown === 'number' && facets.priceBucket.unknown > 0 && (
          <p className="mt-1.5 text-[0.75rem] text-fg-subtle">{facets.priceBucket.unknown} without a published price</p>
        )}
      </Section>

      <Separator />

      {/* ----------------------------------------------------- Society */}
      <Section title="Society">
        <Command className="rounded-md border border-border" shouldFilter value={societyActive} onValueChange={setSocietyActive}>
          <CommandInput placeholder="Search societies…" value={societyQuery} onValueChange={setSocietyQuery} />
          <CommandList className="max-h-64">
            <CommandEmpty>No matches.</CommandEmpty>
            {SOCIETY_KIND_ORDER.map((kind) => {
              const list = societyGroups[kind]
              if (!list.length) return null
              return (
                <CommandGroup key={kind} heading={SOCIETY_KIND_LABEL[kind]}>
                  {list.map((s) => {
                    const checked = filters.society.includes(s.short)
                    const count = facets?.society[s.short]
                    if (facets && !count && !checked) return null
                    return (
                      <CommandItem key={s.short} value={s.name} onSelect={() => toggleInArray('society', s.short)}>
                        <CheckBox checked={checked} />
                        <span className="flex-1 truncate">{s.name}</span>
                        <FacetCount n={count} />
                      </CommandItem>
                    )
                  })}
                </CommandGroup>
              )
            })}
          </CommandList>
        </Command>
      </Section>

      <Separator />

      {/* -------------------------------------------- CPD / abstracts */}
      <Section title="Other">
        <div className="space-y-1">
          <SwitchRow label="CPD accredited" checked={filters.cpd} onToggle={() => onChange({ cpd: !filters.cpd })} />
          <SwitchRow label="Abstracts open" checked={filters.abstractsOpen} onToggle={() => onChange({ abstractsOpen: !filters.abstractsOpen })} />
        </div>
      </Section>
    </div>
  )
}

function countActive(f: DirectoryFilters): number {
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
  if (f.q) n++
  return n
}

function parseIso(iso: string | null): Date | undefined {
  if (!iso) return undefined
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="type-mono-label mb-2 text-fg-subtle">{title}</h3>
      {children}
    </div>
  )
}

function FacetCount({ n }: { n?: number }) {
  if (!n) return null
  return <span className="ml-1 text-fg-subtle">{n}</span>
}

function CheckBox({ checked }: { checked: boolean }) {
  return (
    <span
      className={cn(
        'flex size-4 shrink-0 items-center justify-center rounded-xs border',
        checked ? 'border-brand bg-brand text-fg-onbrand' : 'border-border bg-surface'
      )}
    >
      {checked && <Check className="size-3" strokeWidth={2.5} />}
    </span>
  )
}

function CheckRow({ label, count, checked, onToggle }: { label: string; count?: number; checked: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onToggle}
      className="flex w-full items-center gap-2.5 rounded-sm px-2 py-1.5 text-left text-[0.8125rem] text-fg transition-colors duration-150 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
    >
      <CheckBox checked={checked} />
      <span className="flex-1 truncate">{label}</span>
      {typeof count === 'number' && <span className="type-mono-label text-fg-subtle">{count}</span>}
    </button>
  )
}

function SwitchRow({ label, checked, onToggle }: { label: string; checked: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onToggle}
      className="flex w-full items-center justify-between rounded-sm px-2 py-2 text-[0.8125rem] text-fg transition-colors duration-150 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
    >
      <span>{label}</span>
      <span
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-150',
          checked ? 'border-brand bg-brand' : 'border-border bg-surface-muted'
        )}
      >
        <span
          className={cn(
            'inline-block size-3.5 rounded-full bg-white shadow-xs transition-transform duration-150',
            checked ? 'translate-x-[18px]' : 'translate-x-0.5'
          )}
        />
      </span>
    </button>
  )
}
