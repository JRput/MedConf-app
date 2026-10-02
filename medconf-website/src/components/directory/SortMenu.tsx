'use client'

import { Check, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { DirectorySort } from '@/lib/directory-query'

const OPTIONS: { value: DirectorySort; label: string }[] = [
  { value: 'date', label: 'Date' },
  { value: 'newest', label: 'Newest' },
  { value: 'price', label: 'Price' },
]

export function SortMenu({ value, onChange }: { value: DirectorySort; onChange: (sort: DirectorySort) => void }) {
  const current = OPTIONS.find((o) => o.value === value) ?? OPTIONS[0]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          Sort: {current.label}
          <ChevronDown />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {OPTIONS.map((o) => (
          <DropdownMenuItem key={o.value} onSelect={() => onChange(o.value)}>
            {o.value === value && <Check className="size-4" />}
            {o.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
