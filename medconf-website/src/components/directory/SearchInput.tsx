'use client'

import * as React from 'react'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'

export function SearchInput({ value, onChange, className }: { value: string; onChange: (q: string) => void; className?: string }) {
  const [draft, setDraft] = React.useState(value)
  const debounced = useDebouncedValue(draft, 350)
  const lastSent = React.useRef(value)

  // Keep the input in sync when the URL changes from elsewhere (chip removal,
  // back/forward navigation) without re-triggering our own debounce.
  React.useEffect(() => {
    if (value !== lastSent.current) setDraft(value)
  }, [value])

  React.useEffect(() => {
    if (debounced !== lastSent.current) {
      lastSent.current = debounced
      onChange(debounced)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  return (
    <div className={className}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Search by title, specialty or location…"
          aria-label="Search the directory"
          className="h-10 pl-9"
        />
      </div>
    </div>
  )
}
