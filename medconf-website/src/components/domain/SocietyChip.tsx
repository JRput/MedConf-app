import { cn } from '@/lib/utils'

/**
 * Attribution, not a filter control. The audit found 44 society pills dominating
 * the directory; here the society is a quiet mono label in the row's meta line —
 * present for trust ("this came from the RCP"), never competing with the title.
 */
export function SocietyChip({
  name,
  className,
}: {
  name: string | null | undefined
  className?: string
}) {
  if (!name) return null
  return (
    <span className={cn('type-mono-label text-fg-subtle', className)} title={name}>
      {name}
    </span>
  )
}
