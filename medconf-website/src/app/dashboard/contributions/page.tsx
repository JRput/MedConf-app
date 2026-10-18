'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Loader2 } from 'lucide-react'
import { AccountContainer, AccountEmptyState, AccountPageHeader } from '@/components/account/AccountPageHeader'
import { AddInfoDialog } from '@/components/community/AddInfoDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/hooks/useAuth'
import { useMyContributions } from '@/hooks/useCommunity'
import { createSupabaseClient } from '@/lib/supabase'
import type { AddInfoPayload, Contribution, ContributionStatus } from '@/lib/community/types'
import type { Conference, PricingTier } from '@/lib/types'

const STATUS_META: Record<ContributionStatus, { label: string; variant: 'warning' | 'success' | 'neutral' }> = {
  pending: { label: 'Pending review', variant: 'warning' },
  needs_info: { label: 'Needs info', variant: 'warning' },
  published: { label: 'Published', variant: 'success' },
  merged: { label: 'Merged', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'neutral' },
  hidden: { label: 'Hidden', variant: 'neutral' },
  expired: { label: 'Expired', variant: 'neutral' },
}

interface ConfInfo {
  name: string
  archived: boolean
}

function titleOf(c: Contribution, conf: ConfInfo | undefined): string {
  if (c.kind === 'new_event') {
    const n = (c.payload as unknown as { conference_name?: string }).conference_name
    return n || conf?.name || 'Event submission'
  }
  return conf?.name ?? 'Listing removed'
}

export default function MyContributionsPage() {
  const { user, loading: authLoading } = useAuth()
  const { contributions, loading, error, refresh } = useMyContributions()
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [confs, setConfs] = useState<Map<number, ConfInfo>>(new Map())
  const [editing, setEditing] = useState<{ contribution: Contribution; conference: Conference; tiers: PricingTier[] } | null>(null)
  const [loadingEdit, setLoadingEdit] = useState<string | null>(null)
  const [editError, setEditError] = useState<string | null>(null)

  const confIds = useMemo(
    () => [...new Set(contributions.filter((c) => c.conference_id != null).map((c) => c.conference_id as number))],
    [contributions]
  )

  useEffect(() => {
    if (confIds.length === 0) return
    let cancelled = false
    supabase
      .from('conferences')
      .select('id, conference_name, archived')
      .in('id', confIds)
      .then(({ data }) => {
        if (cancelled) return
        const m = new Map<number, ConfInfo>()
        for (const r of (data ?? []) as { id: number; conference_name: string; archived: boolean | null }[]) {
          m.set(r.id, { name: r.conference_name, archived: r.archived === true })
        }
        setConfs(m)
      })
    return () => {
      cancelled = true
    }
  }, [confIds, supabase])

  const startEdit = async (c: Contribution) => {
    if (c.conference_id == null) return
    setLoadingEdit(c.id)
    setEditError(null)
    const [conf, tiers] = await Promise.all([
      supabase.from('conferences').select('*').eq('id', c.conference_id).maybeSingle(),
      supabase.from('pricing_tiers').select('*').eq('conference_id', c.conference_id),
    ])
    setLoadingEdit(null)
    if (conf.error || !conf.data) {
      setEditError('Could not load the event to edit. Please try again.')
      return
    }
    setEditing({ contribution: c, conference: conf.data as Conference, tiers: (tiers.data ?? []) as PricingTier[] })
  }

  if (!authLoading && !user) {
    return (
      <AccountContainer className="max-w-[920px]">
        <AccountEmptyState
          title="Sign in to see your contributions"
          description="Information you add to events and events you submit are tracked here."
          action={
            <Button size="sm" asChild>
              <Link href="/auth/login">Sign in</Link>
            </Button>
          }
        />
      </AccountContainer>
    )
  }

  return (
    <AccountContainer className="max-w-[920px]">
      <AccountPageHeader
        title="Your contributions"
        subtitle="Everything you have added or submitted, and where it is in review."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/submit">Submit an event</Link>
          </Button>
        }
      />

      {error && (
        <div role="alert" className="mb-4 rounded-lg border border-danger-border bg-danger-subtle px-4 py-3 type-small text-danger-text">
          {error}{' '}
          <button type="button" onClick={refresh} className="font-medium underline underline-offset-2">
            Try again
          </button>
        </div>
      )}
      {editError && (
        <div role="alert" className="mb-4 rounded-lg border border-danger-border bg-danger-subtle px-4 py-3 type-small text-danger-text">
          {editError}
        </div>
      )}

      {loading || authLoading ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : contributions.length === 0 && !error ? (
        <AccountEmptyState
          title="No contributions yet"
          description="Add missing details from any event page, or submit an event that is not listed."
          action={
            <Button variant="outline" size="sm" asChild>
              <Link href="/conferences">Browse the directory</Link>
            </Button>
          }
        />
      ) : (
        <ul className="divide-y divide-border-subtle overflow-hidden rounded-lg border border-border bg-surface">
          {contributions.map((c) => {
            const conf = c.conference_id != null ? confs.get(c.conference_id) : undefined
            const meta = STATUS_META[c.status]
            const live = (c.status === 'published' || c.status === 'merged') && c.conference_id != null
            return (
              <li key={c.id} className="space-y-1.5 px-4 py-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <Badge variant={meta.variant}>{meta.label}</Badge>
                  <span className="min-w-0 flex-1 truncate type-small font-medium text-fg-strong">{titleOf(c, conf)}</span>
                  <span className="type-caption text-fg-subtle">
                    {c.kind === 'new_event' ? 'New event' : 'Added info'} · {new Date(c.created_at).toLocaleDateString()}
                  </span>
                </div>

                {c.moderator_note && (
                  <p className="rounded-md bg-surface-muted px-3 py-2 type-small text-fg-muted">
                    <span className="type-mono-label mr-2 text-fg-subtle">Moderator</span>
                    {c.moderator_note}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  {c.status === 'needs_info' &&
                    (c.kind === 'add_info' ? (
                      <Button type="button" size="sm" disabled={loadingEdit === c.id} aria-busy={loadingEdit === c.id} onClick={() => void startEdit(c)}>
                        {loadingEdit === c.id && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
                        Edit and resubmit
                      </Button>
                    ) : (
                      <Button type="button" size="sm" asChild>
                        <Link href={`/submit?resubmit=${c.id}`}>Edit and resubmit</Link>
                      </Button>
                    ))}
                  {live &&
                    (conf?.archived ? (
                      <span className="type-small text-fg-muted">This event has passed</span>
                    ) : (
                      <Link href={`/conferences/${c.conference_id}`} className="type-small font-medium text-brand-text underline-offset-2 hover:underline">
                        View on MedConf
                      </Link>
                    ))}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {editing && (
        <AddInfoDialog
          conference={editing.conference}
          tiers={editing.tiers}
          open
          onOpenChange={(o) => {
            if (!o) {
              setEditing(null)
              refresh()
            }
          }}
          initialPayload={editing.contribution.payload as AddInfoPayload}
          contributionId={editing.contribution.id}
        />
      )}
    </AccountContainer>
  )
}
