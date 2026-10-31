'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { AlertCircle, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { friendlySubmitError, useSubmitContribution } from '@/hooks/useCommunity'
import { createSupabaseClient } from '@/lib/supabase'
import { todayUtc } from '@/lib/community/schema'
import { clearDraft, loadDraft, saveDraft } from '@/lib/community/submit-draft'
import { emptyFeesDraft, isFeesDraftEmpty, type FeesDraft } from '@/lib/community/fees-draft'
import type { NewEventPayload } from '@/lib/community/types'
import { AccountContainer, AccountPageHeader } from '@/components/account/AccountPageHeader'
import { FeeQuickEditor } from '../FeeQuickEditor'
import { PRESS } from '../press'
import { CollapsibleSection } from './CollapsibleSection'
import { FormSummary } from './FormSummary'
import { SubmitSuccess } from './SubmitSuccess'
import {
  AbstractsCpdSection,
  BasicsSection,
  DescriptionSection,
  LinksSection,
  SpecialtySection,
  WhenSection,
  WhereSection,
  type Ctx,
} from './Sections'
import {
  EMPTY_VALUES,
  KEY_SECTION,
  SECTION_ORDER,
  missingRequired,
  payloadToValues,
  sectionStatuses,
  validateSubmit,
  type SectionId,
  type SubmitValues,
} from './logic'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const DEFAULT_OPEN: SectionId[] = ['basics', 'when', 'where', 'specialty']

type Resubmit =
  | { state: 'none' }
  | { state: 'loading' }
  | { state: 'ready'; id: string; moderatorNote: string | null }
  | { state: 'unavailable' }

export function SubmitEventForm() {
  const { user, loading: authLoading } = useAuth()
  const params = useSearchParams()
  const resubmitParam = params.get('resubmit')
  const resubmitId = resubmitParam && UUID.test(resubmitParam) ? resubmitParam : null

  const supabase = useMemo(() => createSupabaseClient(), [])
  const { submit, submitting } = useSubmitContribution()
  const [updating, setUpdating] = useState(false)

  const [values, setValues] = useState<SubmitValues>(EMPTY_VALUES)
  const [fees, setFees] = useState<FeesDraft>(() => emptyFeesDraft())
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [attempted, setAttempted] = useState(false)
  const [open, setOpen] = useState<Set<SectionId>>(new Set(DEFAULT_OPEN))
  const [serverError, setServerError] = useState<string | null>(null)
  const [done, setDone] = useState<null | { resubmitted: boolean }>(null)
  const [draftRestored, setDraftRestored] = useState(false)
  const [resubmit, setResubmit] = useState<Resubmit>(resubmitId ? { state: 'loading' } : { state: 'none' })
  const [honeypot, setHoneypot] = useState('')
  const ready = useRef(false)
  const formRef = useRef<HTMLFormElement>(null)

  /* ---- restore: resubmit prefill, or local draft ---- */
  useEffect(() => {
    if (authLoading || !user || ready.current) return
    let cancelled = false
    ;(async () => {
      if (resubmitId) {
        const { data, error } = await supabase
          .from('community_contributions')
          .select('id, kind, status, payload, moderator_note')
          .eq('id', resubmitId)
          .eq('user_id', user.id)
          .maybeSingle()
        if (cancelled) return
        if (error || !data || data.status !== 'needs_info' || data.kind !== 'new_event') {
          setResubmit({ state: 'unavailable' })
        } else {
          const { values: v, fees: f } = payloadToValues(data.payload as Partial<NewEventPayload>)
          setValues(v)
          setFees(f)
          setOpen(new Set(SECTION_ORDER.map((s) => s.id)))
          setResubmit({ state: 'ready', id: data.id as string, moderatorNote: (data.moderator_note as string | null) ?? null })
        }
      } else {
        const draft = loadDraft<SubmitValues, FeesDraft>(user.id)
        if (draft) {
          setValues({ ...EMPTY_VALUES, ...draft.values, consent: false })
          setFees(draft.fees)
          setDraftRestored(true)
        }
      }
      ready.current = true
    })()
    return () => {
      cancelled = true
    }
  }, [authLoading, user, resubmitId, supabase])

  /* ---- autosave (debounced) ---- */
  const debouncedDraft = useDebouncedValue({ values, fees }, 800)
  useEffect(() => {
    if (!ready.current || !user || done || resubmitId) return
    const pristine = JSON.stringify(debouncedDraft.values) === JSON.stringify(EMPTY_VALUES) && isFeesDraftEmpty(debouncedDraft.fees)
    if (pristine) return
    saveDraft(user.id, { values: { ...debouncedDraft.values, consent: false }, fees: debouncedDraft.fees })
  }, [debouncedDraft, user, done, resubmitId])

  /* ---- validation ---- */
  const validation = useMemo(() => validateSubmit(values, fees), [values, fees])
  const show = useCallback((k: string) => attempted || touched.has(k), [attempted, touched])
  const err = useCallback((k: string) => (show(k) ? validation.errors[k] : undefined), [show, validation.errors])
  const touch = useCallback((k: string) => setTouched((p) => (p.has(k) ? p : new Set(p).add(k))), [])
  const set = useCallback(<K extends keyof SubmitValues>(k: K, val: SubmitValues[K]) => setValues((p) => ({ ...p, [k]: val })), [])
  const statuses = useMemo(() => sectionStatuses(values, fees, validation.errors, show), [values, fees, validation.errors, show])
  const missing = useMemo(() => missingRequired(values), [values])

  const ctx: Ctx = { v: values, set, err, touch, today: todayUtc() }

  const toggle = (id: SectionId) =>
    setOpen((p) => {
      const n = new Set(p)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  const jump = (id: SectionId) => {
    setOpen((p) => new Set(p).add(id))
    requestAnimationFrame(() => document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  /* ---- submit ---- */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitting || updating) return
    setServerError(null)

    // Honeypot: bots fill the hidden field. Pretend success, send nothing.
    if (honeypot.trim() !== '') {
      if (user) clearDraft(user.id)
      setDone({ resubmitted: false })
      return
    }

    setAttempted(true)
    if (!validation.payload) {
      const bad = new Set<SectionId>()
      for (const k of Object.keys(validation.errors)) if (KEY_SECTION[k]) bad.add(KEY_SECTION[k])
      if (validation.feesInvalid) bad.add('fees')
      setOpen((p) => new Set([...p, ...bad]))
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          const el = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')
          el?.focus()
          el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        })
      )
      return
    }

    const payload = validation.payload
    if (resubmit.state === 'ready') {
      setUpdating(true)
      const { data, error } = await supabase
        .from('community_contributions')
        .update({
          payload,
          note: payload.note ?? null,
          evidence_url: payload.evidence_url ?? null,
          status: 'pending',
        })
        .eq('id', resubmit.id)
        .select('id')
      setUpdating(false)
      if (error || !data || data.length === 0) {
        setServerError(
          error ? friendlySubmitError(error) : 'This submission can no longer be edited. Check your contributions page for its current status.'
        )
        return
      }
      setDone({ resubmitted: true })
      return
    }

    const res = await submit({ kind: 'new_event', payload, note: payload.note ?? null, evidence_url: payload.evidence_url ?? null })
    if (!res.ok) {
      setServerError(res.message)
      return
    }
    if (user) clearDraft(user.id)
    setDone({ resubmitted: false })
  }

  const startAnother = () => {
    setValues(EMPTY_VALUES)
    setFees(emptyFeesDraft())
    setTouched(new Set())
    setAttempted(false)
    setServerError(null)
    setOpen(new Set(DEFAULT_OPEN))
    setDraftRestored(false)
    setDone(null)
    window.scrollTo({ top: 0 })
  }

  const discardDraft = () => {
    if (user) clearDraft(user.id)
    setValues(EMPTY_VALUES)
    setFees(emptyFeesDraft())
    setTouched(new Set())
    setDraftRestored(false)
  }

  /* ---- render ---- */
  const header = (
    <AccountPageHeader
      title={resubmitId ? 'Update your submission' : 'Submit an event'}
      subtitle="Tell us about an event that is not listed. A moderator reviews every submission before it appears."
    />
  )

  if (authLoading) {
    return (
      <AccountContainer>
        {header}
        <p className="type-small text-fg-subtle" role="status">
          Checking your session…
        </p>
      </AccountContainer>
    )
  }

  if (!user) {
    return (
      <AccountContainer>
        {header}
        <div className="max-w-xl space-y-4 rounded-lg border border-border bg-surface-muted p-5">
          <p className="type-body text-fg">Sign in to submit an event. It only takes a moment.</p>
          <div className="flex flex-wrap gap-2">
            <Button asChild size="lg" className={PRESS}>
              <Link href="/auth/login">Sign in</Link>
            </Button>
            <Button asChild size="lg" variant="outline" className={PRESS}>
              <Link href="/auth/signup">Create an account</Link>
            </Button>
          </div>
        </div>
      </AccountContainer>
    )
  }

  if (done) {
    return (
      <AccountContainer>
        <SubmitSuccess resubmitted={done.resubmitted} onAnother={startAnother} />
      </AccountContainer>
    )
  }

  if (resubmit.state === 'unavailable') {
    return (
      <AccountContainer>
        {header}
        <div role="alert" className="max-w-xl space-y-4 rounded-lg border border-border bg-surface-muted p-5">
          <p className="type-body text-fg">This submission is not waiting for changes, or it is not yours, so it cannot be edited here.</p>
          <Button asChild size="lg" className={PRESS}>
            <Link href="/dashboard/contributions">Back to my contributions</Link>
          </Button>
        </div>
      </AccountContainer>
    )
  }

  const busy = submitting || updating
  const isResubmit = resubmit.state === 'ready'

  return (
    <AccountContainer>
      {header}

      {resubmit.state === 'loading' && (
        <p className="type-small text-fg-subtle" role="status">
          Loading your submission…
        </p>
      )}

      {isResubmit && resubmit.moderatorNote && (
        <div role="note" className="mb-5 rounded-lg border border-warn-border bg-warn-subtle p-4">
          <p className="type-caption font-medium text-warn-text">Message from the moderator</p>
          <p className="mt-1 whitespace-pre-line type-body text-fg-strong">{resubmit.moderatorNote}</p>
        </div>
      )}

      {draftRestored && (
        <div role="status" className="mb-5 flex items-center gap-3 rounded-lg border border-border bg-surface-muted py-1 pl-4 pr-1">
          <p className="flex-1 type-small text-fg">Draft restored. Check the details, then send.</p>
          <Button type="button" variant="ghost" size="lg" className={PRESS} onClick={discardDraft}>
            Discard
          </Button>
          <Button type="button" variant="ghost" size="icon-lg" className={PRESS} onClick={() => setDraftRestored(false)} aria-label="Dismiss draft notice">
            <X aria-hidden />
          </Button>
        </div>
      )}

      {resubmit.state !== 'loading' && (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <form ref={formRef} onSubmit={handleSubmit} noValidate className="min-w-0 space-y-3" aria-label="Submit an event">
            {/* Honeypot: hidden from people and assistive tech; bots fill it. */}
            <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
              <label htmlFor="sub-website">Website</label>
              <input id="sub-website" name="website" type="text" tabIndex={-1} autoComplete="off" value={honeypot} onChange={(e) => setHoneypot(e.target.value)} />
            </div>

            {SECTION_ORDER.map((s, i) => {
              const status = statuses.find((x) => x.id === s.id)!
              return (
                <CollapsibleSection key={s.id} id={s.id} index={i + 1} status={status} open={open.has(s.id)} onToggle={() => toggle(s.id)}>
                  {s.id === 'basics' && <BasicsSection ctx={ctx} />}
                  {s.id === 'when' && <WhenSection ctx={ctx} />}
                  {s.id === 'where' && <WhereSection ctx={ctx} />}
                  {s.id === 'specialty' && <SpecialtySection ctx={ctx} />}
                  {s.id === 'fees' && (
                    <>
                      <p className="type-small text-fg-muted">Optional. Add what you know; fees become public once approved.</p>
                      <FeeQuickEditor value={fees} onChange={setFees} showAllErrors={attempted} idPrefix="sub-fees" />
                    </>
                  )}
                  {s.id === 'abstracts' && <AbstractsCpdSection ctx={ctx} />}
                  {s.id === 'description' && <DescriptionSection ctx={ctx} />}
                  {s.id === 'links' && <LinksSection ctx={ctx} />}
                </CollapsibleSection>
              )
            })}

            <div className="space-y-3 rounded-lg border border-border bg-surface p-4 sm:p-5">
              <label className="flex min-h-11 cursor-pointer items-start gap-2.5 type-small text-fg">
                <input
                  id="sub-consent"
                  type="checkbox"
                  className="mt-0.5 size-4 shrink-0 cursor-pointer accent-brand"
                  checked={values.consent}
                  onChange={(e) => {
                    set('consent', e.target.checked)
                    touch('consent')
                  }}
                  aria-invalid={!!err('consent')}
                  aria-describedby={err('consent') ? 'sub-consent-error' : undefined}
                />
                The information is public, accurate to my knowledge, and MedConf may edit or decline it. See our{' '}
                <Link href="/terms" target="_blank" className="underline underline-offset-2">Terms</Link> and{' '}
                <Link href="/privacy" target="_blank" className="underline underline-offset-2">Privacy Policy</Link>.
              </label>
              {err('consent') && (
                <p id="sub-consent-error" role="alert" className="type-caption text-danger-text">
                  {err('consent')}
                </p>
              )}

              {serverError && (
                <div role="alert" className="flex items-start gap-2 rounded-md border border-danger-border bg-danger-subtle p-3 type-small text-danger-text">
                  <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {serverError}
                </div>
              )}

              <p className="type-caption text-fg-subtle lg:hidden" aria-live="polite">
                {missing.length === 0 ? 'All required details are in.' : `Still required: ${missing.join(', ')}.`}
              </p>

              <Button type="submit" size="lg" className={`${PRESS} w-full sm:w-auto`} disabled={busy}>
                {busy && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
                {busy ? 'Sending…' : isResubmit ? 'Resubmit for review' : 'Submit for review'}
              </Button>
            </div>
          </form>

          <div className="hidden lg:sticky lg:top-24 lg:block">
            <FormSummary statuses={statuses} missing={missing} onJump={jump} />
          </div>
        </div>
      )}
    </AccountContainer>
  )
}
