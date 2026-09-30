'use client'

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useAccent, type Accent } from './AccentProvider'

const SWATCH: Record<Accent, string> = {
  // Inline swatches deliberately bypass the token layer — they must show the
  // candidate colour regardless of which accent is currently active.
  teal: '#0f766e',
  ink: '#1e3a8a',
}

/** W1 review control. Deleted once the owner picks an accent. */
export function AccentToggle() {
  const { accent, setAccent } = useAccent()

  return (
    <ToggleGroup
      type="single"
      value={accent}
      onValueChange={(v) => v && setAccent(v as Accent)}
      variant="outline"
      size="sm"
      aria-label="Brand accent"
      className="rounded-md"
    >
      {(Object.keys(SWATCH) as Accent[]).map((a) => (
        <ToggleGroupItem key={a} value={a} aria-label={`${a} accent`} className="px-2.5 capitalize">
          <span
            className="size-2.5 rounded-xs ring-1 ring-black/10"
            style={{ backgroundColor: SWATCH[a] }}
            aria-hidden
          />
          {a}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
