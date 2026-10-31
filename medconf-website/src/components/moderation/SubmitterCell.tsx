import type { Submitter } from '@/hooks/useModeration'
import { cn } from '@/lib/utils'

/**
 * Admin-only submitter identity. Falls back to a short monospace id while the
 * admin SELECT policy on user_profiles is not in place. Never used publicly.
 */
export function SubmitterCell({ userId, submitter, className }: { userId: string | null; submitter: Submitter | null; className?: string }) {
  if (userId == null) {
    return <span className={cn('block truncate type-small text-fg-muted', className)}>Deleted account</span>
  }
  const label = submitter?.email || submitter?.full_name
  if (label) {
    return (
      <span className={cn('block truncate type-small text-fg', className)} title={submitter?.email ?? undefined}>
        {label}
      </span>
    )
  }
  return (
    <span className={cn('block truncate font-mono text-xs text-fg-muted', className)} title={userId}>
      {userId.slice(0, 8)}
    </span>
  )
}
