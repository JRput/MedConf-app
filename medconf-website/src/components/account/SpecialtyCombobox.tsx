'use client'

import * as React from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'
import { cn } from '@/lib/utils'

/**
 * Searchable specialty picker shared by onboarding and settings — both write
 * the canonical parent slug (see ../../lib/taxonomy/specialties.ts) to
 * `user_profiles.specialty`, which `queryDirectory`'s `specialty` filter
 * already expects (it expands a parent slug to every raw DB value that maps
 * to it). "Other" is pinned last rather than sorted by its order number with
 * the rest, since it's a catch-all, not a real 32nd specialty.
 */
export function SpecialtyCombobox({
  value,
  onChange,
  placeholder = 'Select a specialty…',
}: {
  value: string | null
  onChange: (slug: string) => void
  placeholder?: string
}) {
  const [open, setOpen] = React.useState(false)
  const selected = SPECIALTY_PARENTS.find((p) => p.slug === value)
  const ordered = React.useMemo(
    () => [...SPECIALTY_PARENTS.filter((p) => p.slug !== 'other'), ...SPECIALTY_PARENTS.filter((p) => p.slug === 'other')],
    []
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between font-normal"
        >
          {selected ? selected.label : <span className="text-fg-subtle">{placeholder}</span>}
          <ChevronsUpDown className="size-4 shrink-0 text-fg-subtle" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search specialties…" />
          <CommandList>
            <CommandEmpty>No specialty found.</CommandEmpty>
            <CommandGroup>
              {ordered.map((p) => (
                <CommandItem
                  key={p.slug}
                  value={p.label}
                  onSelect={() => {
                    onChange(p.slug)
                    setOpen(false)
                  }}
                >
                  <Check className={cn('size-4', p.slug === value ? 'opacity-100' : 'opacity-0')} />
                  {p.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
