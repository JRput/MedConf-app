'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { AccountContainer, AccountEmptyState } from '@/components/account/AccountPageHeader'
import { ActionBar } from '@/components/moderation/ActionBar'
import { DuplicatesPanel } from '@/components/moderation/DuplicatesPanel'
import { EnrichmentChip } from '@/components/moderation/EnrichmentChip'
import { FieldReviewTable } from '@/components/moderation/FieldReviewTable'
import { UncheckedConfirm } from '@/components/moderation/UncheckedConfirm'
import { MergePicker } from '@/components/moderation/MergePicker'
import { SubmitterCell } from '@/components/moderation/SubmitterCell'
import { TierReviewTable } from '@/components/moderation/TierReviewTable'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useIsAdmin } from '@/hooks/useIsAdmin'
import { useContribution, useModerate, type ModerationAction, type QueueItem } from '@/hooks/useModeration'
import { feesDraftToRaw, isFeesDraftEmpty, validateFeesDraft, type FeesDraft } from '@/lib/community/fees-draft'
import {
  buildFieldRows,
  buildFinalPayload,
  canApprove,
  disagreementFields,
  feesPayloadToDraft,
  finalProblems,
  isAddInfo,
  needsOverride,
  rejectedUrls,
  safeHref,
  userFields,
  type DuplicateRow,
  type EditMap,
} from '@/lib/community/moderation'
import type { FeesPayload } from '@/lib/community/types'

const STATUS_VARIANT = {
  pending: 'warning',
  needs_info: 'warning',
  published: 'success',
  merged: 'success',
  rejected: 'neutral',
  hidden: 'neutral',
  expired: 'neutral',
} as const

export default function ModerationItemPage() {
  const isAdmin = useIsAdmin()
  const params = useParams<{ id: string }>()

  if (isAdmin === null) {
    return (
      <AccountContainer>
        <Skeleton className="h-10 w-64" />
      </AccountContainer>
    )
  }
  if (!isAdmin) {
    return (
      <AccountContainer className="max-w-[640px]">
        <AccountEmptyState title="Admins only" description="This area is for MedConf moderators. If you should have access, ask the site owner to flag your account." />
      </AccountContainer>
    )
  }
  return <Item id={params.id} />
}

function Item({ id }: { id: string }) {
  const { item, loading, error, refresh } = useContribution(id)

  if (loading && !item) {
    return (
      <AccountContainer>
        <div className="space-y-3" aria-busy>
          <Skeleton className="h-8 w-80" />
          <Skeleton className="h-64 w-full" />
        </div>
      </AccountContainer>
    )
  }
  if (!item) {
    return (
      <AccountContainer className="max-w-[640px]">
        <BackLink />
        <AccountEmptyState title="Not found" description={error ?? 'This contribution does not exist or you cannot see it.'} />
      </AccountContainer>
    )
  }
  return <Review key={item.id} item={item} refresh={refresh} />
}

function BackLink() {
  return (
    <Link
      href="/admin/moderation"
      className="mb-4 inline-flex min-h-11 items-center gap-1.5 type-small font-medium text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ArrowLeft className="size-4" aria-hidden />
      Moderation
    </Link>
  )
}

function ExtLink({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (!href) return null
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex min-h-8 items-center gap-1 type-small font-medium text-brand-text underline-offset-2 hover:underline"
    >
      {children}
      <ExternalLink className="size-3.5" aria-hidden />
    </a>
  )
}

function Review({ item, refresh }: { item: QueueItem; refresh: () => void }) {
  const { run, busy } = useModerate()
  const open = item.status === 'pending' || item.status === 'needs_info'
  const addInfo = isAddInfo(item.payload)
  // Closed items show what was actually approved when we have it.
  const source = open ? item.payload : item.final_payload ?? item.payload

  const [fieldEdits, setFieldEdits] = useState<EditMap>({})
  const initialFees = useMemo(
    () => buildFinalPayload(source, item.enrichment).final.fees as FeesPayload | undefined,
    [source, item.enrichment]
  )
  const [draft, setDraft] = useState<FeesDraft>(() => feesPayloadToDraft(initialFees))
  const [feesTouched, setFeesTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicateOf, setDuplicateOf] = useState<number | null>(null)
  const [outcome, setOutcome] = useState<{ label: string; conferenceId: number | null } | null>(null)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergePre, setMergePre] = useState<DuplicateRow | null>(null)
  // An approve/merge waiting for the "unchecked link" confirmation.
  const [confirmUnchecked, setConfirmUnchecked] = useState<{ verb: 'Approve' | 'Merge'; run: () => Promise<boolean> } | null>(null)

  // Fees edit: untouched = whatever buildFinalPayload defaults to; empty draft = no fees.
  const feesCheck = useMemo(() => {
    if (isFeesDraftEmpty(draft)) return { payload: null as FeesPayload | null, invalid: false }
    const v = validateFeesDraft(draft)
    if (!v.payload) return { payload: null, invalid: true }
    return { payload: feesDraftToRaw(draft) as FeesPayload, invalid: false }
  }, [draft])

  const edits: EditMap = useMemo(() => ({ ...fieldEdits, fees: feesCheck.payload }), [fieldEdits, feesCheck])
  const rows = useMemo(() => buildFieldRows(source, item.enrichment, fieldEdits), [source, item.enrichment, fieldEdits])
  const built = useMemo(() => buildFinalPayload(source, item.enrichment, edits), [source, item.enrichment, edits])
  const problems = useMemo(() => {
    const p = finalProblems(source, built.final)
    if (feesCheck.invalid) p.push('Fix the fee table errors.')
    return p
  }, [source, built, feesCheck.invalid])
  const check = canApprove(item)
  const rejected = useMemo(() => rejectedUrls(item.enrichment), [item.enrichment])
  const finalOrganiser = (addInfo ? (built.final.fields as Record<string, unknown> | undefined)?.organiser_url : built.final.organiser_url) as string | undefined
  const override = needsOverride(item, finalOrganiser)
  const differs = useMemo(() => disagreementFields(item.enrichment, userFields(source)), [item.enrichment, source])
  const user = userFields(item.payload)
  const userFeesPayload = (item.payload as unknown as { fees?: FeesPayload }).fees
  const feesPrefilled = open && !feesTouched && built.prefilled.includes('fees')

  const organiserHref = safeHref(user.organiser_url)
  const evidenceHref = safeHref(item.evidence_url ?? (item.payload as unknown as { evidence_url?: string }).evidence_url)
  const submitterNote = item.note ?? (item.payload as unknown as { note?: string }).note

  const act = async (
    action: ModerationAction,
    opts: { note?: string; final?: Record<string, unknown> } = {},
    label: string
  ): Promise<boolean> => {
    setError(null)
    setDuplicateOf(null)
    const res = await run(item.id, action, opts)
    if (res.ok) {
      toast.success(label)
      setOutcome({ label, conferenceId: res.conferenceId })
      refresh()
      return true
    }
    if (res.code === 'duplicate') {
      setDuplicateOf(res.conferenceId)
      return false
    }
    setError(res.message)
    return false
  }

  const doApprove = (unchecked: boolean) =>
    act('approve', { final: unchecked ? { ...built.final, approve_unchecked: true } : built.final }, 'Approved and published')

  const doMerge = (conferenceId: number, unchecked: boolean) =>
    act(
      'merge',
      { final: { ...built.final, merge_into_conference_id: conferenceId, ...(unchecked ? { approve_unchecked: true } : {}) } },
      `Merged into #${conferenceId}`
    ).then((ok) => {
      if (ok) setMergeOpen(false)
      return ok
    })

  const mergeInto = (conferenceId: number) => {
    if (override.needed) {
      setConfirmUnchecked({ verb: 'Merge', run: () => doMerge(conferenceId, true) })
      return Promise.resolve(false)
    }
    return doMerge(conferenceId, false)
  }

  const searchSeed = typeof user.conference_name === 'string' ? user.conference_name : item.eventName

  return (
    <AccountContainer className="pb-6">
      <BackLink />

      <header className="mb-5 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {item.kind === 'new_event' ? <Badge variant="brand">New event</Badge> : <Badge variant="neutral">Add info</Badge>}
          <Badge variant={STATUS_VARIANT[item.status]}>{item.status.replace('_', ' ')}</Badge>
          <EnrichmentChip status={item.enrichment_status} />
          <span className="type-caption text-fg-subtle">Submitted {new Date(item.created_at).toLocaleString()}</span>
        </div>
        <h1 className="type-h1 text-fg-strong">{item.eventName}</h1>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
          <span className="flex items-center gap-2 type-small text-fg-muted">
            By <SubmitterCell userId={item.user_id} submitter={item.submitter} className="max-w-64" />
          </span>
          <ExtLink href={organiserHref}>Organiser page</ExtLink>
          <ExtLink href={evidenceHref}>Evidence</ExtLink>
          {addInfo && item.conference_id != null && (
            <a href={`/conferences/${item.conference_id}`} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-8 items-center gap-1 type-small font-medium text-brand-text underline-offset-2 hover:underline">
              Existing listing #{item.conference_id}
              <ExternalLink className="size-3.5" aria-hidden />
            </a>
          )}
          {!addInfo && item.conference_id != null && (
            <Link href={`/conferences/${item.conference_id}`} className="type-small font-medium text-brand-text underline-offset-2 hover:underline">
              View listing #{item.conference_id}
            </Link>
          )}
        </div>
      </header>

      <div className="space-y-5">
        {outcome && (
          <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-ok-border bg-ok-subtle px-4 py-3 type-small text-ok-text">
            <span>{outcome.label}.</span>
            {outcome.conferenceId != null && (
              <Link href={`/conferences/${outcome.conferenceId}`} className="font-medium underline underline-offset-2">
                View listing
              </Link>
            )}
          </div>
        )}

        {(submitterNote || item.moderator_note) && (
          <div className="grid gap-3 md:grid-cols-2">
            {submitterNote && (
              <div className="rounded-lg border border-border bg-surface p-4">
                <p className="mb-1 type-mono-label text-fg-subtle">Message from submitter</p>
                <p className="whitespace-pre-wrap break-words type-small text-fg">{submitterNote}</p>
              </div>
            )}
            {item.moderator_note && (
              <div className="rounded-lg border border-border bg-surface p-4">
                <p className="mb-1 type-mono-label text-fg-subtle">Moderator note</p>
                <p className="whitespace-pre-wrap break-words type-small text-fg">{item.moderator_note}</p>
              </div>
            )}
          </div>
        )}

        {open && differs.length > 0 && (
          <p className="type-small text-warn-text">
            The organiser site disagrees on {differs.length} {differs.length === 1 ? 'field' : 'fields'}: {differs.join(', ')}.
          </p>
        )}

        <section aria-labelledby="fields-title" className="space-y-2">
          <h2 id="fields-title" className="type-h3 text-fg-strong">
            Fields
          </h2>
          <fieldset disabled={!open || busy} className="m-0 min-w-0 border-0 p-0">
            <FieldReviewTable
              rows={rows}
              edits={fieldEdits}
              hasEnrichment={item.enrichment_status === 'fetched'}
              onEdit={(field, value) => {
                setError(null)
                setFieldEdits((p) => ({ ...p, [field]: value }))
              }}
            />
          </fieldset>
        </section>

        {(userFeesPayload || foundHasPricing(item) || !isFeesDraftEmpty(draft) || open) && (
          <section aria-labelledby="fees-title" className="space-y-2">
            <h2 id="fees-title" className="type-h3 text-fg-strong">
              Fees
            </h2>
            <fieldset disabled={!open || busy} className="m-0 min-w-0 border-0 p-0">
              <TierReviewTable
                userFees={userFeesPayload}
                enrichment={item.enrichment}
                draft={draft}
                onDraft={(d) => {
                  setError(null)
                  setFeesTouched(true)
                  setDraft(d)
                }}
                prefilled={feesPrefilled}
                disagrees={differs.includes('fees')}
                onKeep={() => setFeesTouched(true)}
              />
            </fieldset>
          </section>
        )}

        {open && item.kind === 'new_event' && (
          <DuplicatesPanel
            payload={item.payload}
            disabled={busy}
            onMerge={(row) => {
              setMergePre(row)
              setMergeOpen(true)
            }}
          />
        )}

        <ActionBar
          item={item}
          check={check}
          override={override}
          rejected={rejected}
          problems={open ? problems : []}
          busy={busy}
          error={error}
          duplicateOf={duplicateOf}
          onApprove={() => {
            if (override.needed) setConfirmUnchecked({ verb: 'Approve', run: () => doApprove(true) })
            else void doApprove(false)
          }}
          onReason={(action, reason) =>
            act(action, { note: reason }, action === 'needs_info' ? 'Information requested' : action === 'reject' ? 'Rejected' : 'Hidden')
          }
          onOpenMerge={() => {
            setMergePre(null)
            setMergeOpen(true)
          }}
          onMergeInto={(cid) => void mergeInto(cid)}
        />
      </div>

      <UncheckedConfirm
        open={confirmUnchecked !== null}
        onOpenChange={(o) => !o && setConfirmUnchecked(null)}
        reason={override.reason}
        verb={confirmUnchecked?.verb ?? 'Approve'}
        busy={busy}
        onConfirm={async () => {
          const pending = confirmUnchecked
          if (!pending) return
          await pending.run()
          setConfirmUnchecked(null)
        }}
      />

      <MergePicker
        open={mergeOpen}
        onOpenChange={setMergeOpen}
        preselected={mergePre}
        initialQuery={searchSeed}
        busy={busy}
        onConfirm={(cid) => void mergeInto(cid)}
      />
    </AccountContainer>
  )
}

function foundHasPricing(item: QueueItem): boolean {
  const p = item.enrichment?.pricing
  return !!p && Array.isArray(p.value) && p.value.length > 0
}
