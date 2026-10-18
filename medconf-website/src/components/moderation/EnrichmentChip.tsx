import { Badge } from '@/components/ui/badge'
import type { EnrichmentStatus } from '@/lib/community/types'

const META: Record<EnrichmentStatus, { label: string; variant: 'neutral' | 'success' | 'warning' | 'danger'; title: string }> = {
  waiting: { label: 'Waiting', variant: 'neutral', title: 'The organiser-site check has not run yet.' },
  fetched: { label: 'Checked', variant: 'success', title: 'Organiser site fetched and compared.' },
  blocked: { label: 'Blocked', variant: 'warning', title: 'The organiser site blocked the automatic check.' },
  failed: { label: 'Failed', variant: 'danger', title: 'The automatic check failed.' },
  skipped: { label: 'Unsafe URL', variant: 'danger', title: 'The URL was rejected as unsafe. This cannot be approved.' },
}

/** Organiser-site check state. Always text, never colour alone. */
export function EnrichmentChip({ status }: { status: EnrichmentStatus }) {
  const m = META[status] ?? META.waiting
  return (
    <Badge variant={m.variant} title={m.title}>
      {m.label}
    </Badge>
  )
}
