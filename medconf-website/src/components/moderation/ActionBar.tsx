'use client'

import { useState } from 'react'
import { AlertCircle, AlertTriangle, Check, EyeOff, GitMerge, Loader2, MessageCircleQuestion, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { QueueItem } from '@/hooks/useModeration'
import type { ApprovalCheck, OverrideCheck } from '@/lib/community/moderation'
import { ReasonDialog } from './ReasonDialog'

type Pending = 'needs_info' | 'reject' | 'hide' | null

const COPY: Record<Exclude<Pending, null>, { title: string; description: string; confirm: string; destructive: boolean }> = {
  needs_info: {
    title: 'Request more information',
    description: 'The submitter sees this message and can edit and resubmit.',
    confirm: 'Send request',
    destructive: false,
  },
  reject: {
    title: 'Reject this contribution',
    description: 'The submitter sees this reason. Nothing is published.',
    confirm: 'Reject',
    destructive: true,
  },
  hide: {
    title: 'Hide this contribution',
    description: 'It is removed from the public listing. The submitter sees this reason.',
    confirm: 'Hide',
    destructive: true,
  },
}

/** Sticky decision bar. Approve is primary; request info, reject and hide ask for a reason. */
export function ActionBar({
  item,
  check,
  override,
  rejected,
  problems,
  busy,
  error,
  duplicateOf,
  onApprove,
  onReason,
  onOpenMerge,
  onMergeInto,
}: {
  item: QueueItem
  check: ApprovalCheck
  override: OverrideCheck
  /** URLs the safety check rejected; they are removed from what gets published. */
  rejected: string[]
  problems: string[]
  busy: boolean
  error: string | null
  duplicateOf: number | null
  onApprove: () => void
  onReason: (action: Exclude<Pending, null>, reason: string) => Promise<boolean>
  onOpenMerge: () => void
  onMergeInto: (conferenceId: number) => void
}) {
  const [pending, setPending] = useState<Pending>(null)
  const open = item.status === 'pending' || item.status === 'needs_info'
  const canHide = item.status === 'published' || item.status === 'merged'

  if (!open && !canHide) {
    return (
      <p className="rounded-lg border border-border bg-surface-muted px-4 py-3 type-small text-fg-muted">
        This item is {item.status.replace('_', ' ')}. No further action is available.
      </p>
    )
  }

  const approveBlocked = !check.ok || problems.length > 0
  const copy = pending ? COPY[pending] : null

  return (
    <div className="sticky bottom-0 z-30 -mx-4 flex flex-col gap-3 border-t border-border bg-bg px-4 py-3 sm:mx-0 sm:rounded-lg sm:border">
      <div aria-live="polite" className="space-y-2 empty:hidden">
        {open && !check.ok && (
          <Notice tone="danger" icon={<AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            {check.reason}
          </Notice>
        )}
        {open && rejected.length > 0 && (
          <Notice tone="warn" icon={<AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            <span>
              These links were rejected by the safety check and will not be published:
              <ul className="mt-1 list-disc space-y-0.5 pl-5 break-all font-mono text-xs">
                {rejected.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </span>
          </Notice>
        )}
        {open && check.ok && override.needed && (
          <Notice tone="warn" icon={<AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            {override.reason} Approving now publishes it unchecked.
          </Notice>
        )}
        {open && check.ok && !override.needed && check.warning && (
          <Notice tone="warn" icon={<AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            {check.warning}
          </Notice>
        )}
        {open && check.ok && problems.length > 0 && (
          <Notice tone="danger" icon={<AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            {problems.join(' ')}
          </Notice>
        )}
        {duplicateOf !== null && (
          <Notice tone="warn" icon={<AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              Already listed as #{duplicateOf}.
              <Button type="button" size="xs" variant="outline" disabled={busy} onClick={() => onMergeInto(duplicateOf)}>
                Merge into #{duplicateOf}
              </Button>
            </span>
          </Notice>
        )}
        {error && (
          <Notice tone="danger" icon={<AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}>
            {error}
          </Notice>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {open && (
          <>
            <Button type="button" size="lg" disabled={busy || approveBlocked} aria-busy={busy} onClick={onApprove}>
              {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <Check aria-hidden />}
              {override.needed ? 'Approve anyway…' : 'Approve'}
            </Button>
            <Button type="button" size="lg" variant="outline" disabled={busy} onClick={() => setPending('needs_info')}>
              <MessageCircleQuestion aria-hidden />
              Request info
            </Button>
            <Button
              type="button"
              size="lg"
              variant="outline"
              disabled={busy}
              onClick={() => setPending('reject')}
              className="text-danger-text hover:border-danger-border hover:bg-danger-subtle hover:text-danger-text"
            >
              <XCircle aria-hidden />
              Reject
            </Button>
            {item.kind === 'new_event' && (
              <Button type="button" size="lg" variant="outline" disabled={busy} onClick={onOpenMerge}>
                <GitMerge aria-hidden />
                Merge
              </Button>
            )}
          </>
        )}
        {canHide && (
          <Button
            type="button"
            size="lg"
            variant="outline"
            disabled={busy}
            onClick={() => setPending('hide')}
            className="text-danger-text hover:border-danger-border hover:bg-danger-subtle hover:text-danger-text"
          >
            <EyeOff aria-hidden />
            Hide
          </Button>
        )}
      </div>

      {copy && pending && (
        <ReasonDialog
          open
          onOpenChange={(o) => !o && setPending(null)}
          title={copy.title}
          description={copy.description}
          confirmLabel={copy.confirm}
          destructive={copy.destructive}
          busy={busy}
          onConfirm={async (reason) => {
            const ok = await onReason(pending, reason)
            if (ok) setPending(null)
          }}
        />
      )}
    </div>
  )
}

function Notice({ tone, icon, children }: { tone: 'danger' | 'warn'; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={
        tone === 'danger'
          ? 'flex items-start gap-2 rounded-md border border-danger-border bg-danger-subtle px-3 py-2 type-small text-danger-text'
          : 'flex items-start gap-2 rounded-md border border-warn-border bg-warn-subtle px-3 py-2 type-small text-warn-text'
      }
    >
      {icon}
      <span>{children}</span>
    </div>
  )
}
